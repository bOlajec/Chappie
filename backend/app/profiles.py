"""Saved conversation profiles and tool-access preferences."""
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from . import db

ReasoningMode = Literal['off', 'on', 'model_default']


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default='', max_length=300)
    instructions: str = Field(default='', max_length=12000)
    project_context: str = Field(default='', max_length=12000)
    reference_notes: str = Field(default='', max_length=24000)
    preferred_model: str = Field(default='', max_length=200)
    reasoning: ReasoningMode = 'off'
    script_tools_enabled: bool = False

    @field_validator('name')
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError('Assistant name must not be blank')
        return value.strip()


class ChatAssistantInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    assistant_id: str | None = Field(default=None, max_length=100)
    project_context: str | None = Field(default=None, max_length=12000)


class ChatContextInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_context: str = Field(max_length=12000)


def profile_data(profile):
    return {key: getattr(profile, key) for key in ('id', 'name', 'description', 'instructions',
        'project_context', 'reference_notes', 'preferred_model', 'reasoning', 'updated_at', 'script_tools_enabled')}


def assign_assistant(session, chat, body: ChatAssistantInput):
    if body.assistant_id is None:
        chat.assistant_id, chat.assistant_snapshot = None, None
        chat.project_context = body.project_context or ''
        chat.reasoning = 'off'
        chat.script_tools_enabled = False
    else:
        profile = session.get(db.AssistantProfile, body.assistant_id)
        if not profile:
            raise HTTPException(404, 'Assistant profile not found')
        chat.assistant_id, chat.assistant_snapshot = profile.id, profile_data(profile)
        chat.project_context = profile.project_context if body.project_context is None else body.project_context
        chat.reasoning = profile.reasoning
        chat.script_tools_enabled = profile.script_tools_enabled
        if profile.preferred_model:
            chat.model = profile.preferred_model
    chat.updated_at = db.now()


router = APIRouter(prefix='/api/assistants', tags=['Assistant profiles'])


@router.get('')
def list_profiles():
    with db.Session() as session:
        return [profile_data(p) for p in session.scalars(select(db.AssistantProfile).order_by(db.AssistantProfile.name, db.AssistantProfile.id))]


@router.post('', status_code=201)
def create_profile(body: ProfileInput):
    with db.Session.begin() as session:
        profile = db.AssistantProfile(**body.model_dump())
        session.add(profile)
        session.flush()
        return profile_data(profile)


@router.put('/{profile_id}')
def update_profile(profile_id: str, body: ProfileInput):
    with db.Session.begin() as session:
        profile = session.get(db.AssistantProfile, profile_id)
        if not profile:
            raise HTTPException(404, 'Assistant profile not found')
        for key, value in body.model_dump().items():
            setattr(profile, key, value)
        profile.updated_at = db.now()
        return profile_data(profile)


@router.delete('/{profile_id}', status_code=204)
def delete_profile(profile_id: str):
    with db.Session.begin() as session:
        profile = session.get(db.AssistantProfile, profile_id)
        if not profile:
            raise HTTPException(404, 'Assistant profile not found')
        # Preserve each chat's copied instructions and context after profile deletion.
        session.execute(update(db.Chat).where(db.Chat.assistant_id == profile_id).values(assistant_id=None))
        session.delete(profile)
