import asyncio
from contextlib import asynccontextmanager
from time import monotonic
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from .db import Chat, Message, Session, now
from . import ollama
from .config import settings
from .prompts import assistant_system_prompt
from .profiles import router as profiles_router, ChatAssistantInput, ChatContextInput, assign_assistant
from .chat_stream import stream_chat
from .tools import scripts
from .tools.history import history_messages

# One Uvicorn worker is intentional for this milestone; see README.
active_chats: set[str] = set()


@asynccontextmanager
async def lifespan(app):
    with Session.begin() as db:
        db.execute(update(Message).where(Message.status == 'streaming').values(status='interrupted'))
    yield


app = FastAPI(title='Local LLM Interface', lifespan=lifespan)
app.include_router(profiles_router)


class SendMessage(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100000)
    think: bool | None = None
    use_scripts: bool | None = None


def chat_data(chat, full=False):
    data = {key: getattr(chat, key) for key in ('id', 'title', 'model', 'updated_at', 'assistant_id', 'reasoning', 'script_tools_enabled')}
    data['assistant_name'] = chat.assistant_snapshot.get('name') if chat.assistant_snapshot else None
    if full:
        data.update(assistant_snapshot=chat.assistant_snapshot, project_context=chat.project_context)
    return data


def message_data(message):
    return {key: getattr(message, key) for key in ('id', 'role', 'content', 'model', 'status', 'created_at', 'tool_calls', 'tool_name')}


@app.get('/api/health')
def health():
    return {'status': 'ok'}


@app.get('/api/diagnostics')
async def diagnostics():
    return await ollama.diagnostics()


@app.get('/api/models')
async def models():
    try:
        return {'models': await ollama.installed_models()}
    except Exception as exc:
        raise HTTPException(502, f'Cannot list Ollama models: {exc}') from exc


@app.get('/api/scripts')
async def saved_scripts():
    if not settings.script_tools_enabled:
        return {'enabled': False, 'available': False, 'scripts': [], 'detail': 'Saved scripts are disabled in server configuration'}
    try:
        entries = await scripts.catalog()
        return {'enabled': True, 'available': True, 'scripts': entries, 'detail': 'Registered Python scripts run in the separate runner'}
    except Exception as exc:
        return {'enabled': True, 'available': False, 'scripts': [], 'detail': f'Script runner unavailable: {exc}'}


@app.get('/api/chats')
def chats():
    with Session() as db:
        return [chat_data(c) for c in db.scalars(select(Chat).order_by(Chat.updated_at.desc()))]


@app.get('/api/model-info')
async def model_info(model: str = Query(min_length=1, max_length=200)):
    try:
        return await ollama.model_info(model)
    except Exception as exc:
        raise HTTPException(502, f'Cannot inspect Ollama model: {exc}') from exc


@app.post('/api/chats', status_code=201)
def create_chat(body: ChatAssistantInput | None = None):
    with Session.begin() as db:
        chat = Chat()
        assign_assistant(db, chat, body or ChatAssistantInput())
        db.add(chat)
        db.flush()
        return chat_data(chat, full=True)


@app.get('/api/chats/{chat_id}')
def get_chat(chat_id: str):
    with Session() as db:
        chat = db.get(Chat, chat_id)
        if not chat:
            raise HTTPException(404, 'Chat not found')
        return {**chat_data(chat, full=True), 'messages': [message_data(m) for m in db.scalars(select(Message).where(Message.chat_id == chat_id).order_by(Message.id))]}


@app.patch('/api/chats/{chat_id}/assistant')
async def change_assistant(chat_id: str, body: ChatAssistantInput):
    if chat_id in active_chats:
        raise HTTPException(409, 'Wait for the response to finish before changing the assistant')
    with Session.begin() as db:
        chat = db.get(Chat, chat_id)
        if not chat:
            raise HTTPException(404, 'Chat not found')
        assign_assistant(db, chat, body)
        return chat_data(chat, full=True)


@app.patch('/api/chats/{chat_id}/context')
async def change_project_context(chat_id: str, body: ChatContextInput):
    if chat_id in active_chats:
        raise HTTPException(409, 'Wait for the response to finish before editing project context')
    with Session.begin() as db:
        chat = db.get(Chat, chat_id)
        if not chat:
            raise HTTPException(404, 'Chat not found')
        chat.project_context, chat.updated_at = body.project_context, now()
        return chat_data(chat, full=True)


@app.post('/api/chats/{chat_id}/messages')
async def send(chat_id: str, body: SendMessage):
    started = monotonic()
    if not body.content.strip() or not body.model.strip():
        raise HTTPException(422, 'Message and model must not be blank')
    if chat_id in active_chats:
        raise HTTPException(409, 'This chat is already generating a response')
    with Session() as db:
        chat = db.get(Chat, chat_id)
        if not chat:
            raise HTTPException(404, 'Chat not found')
        requested_scripts = chat.script_tools_enabled if body.use_scripts is None else body.use_scripts
    active_chats.add(chat_id)
    try:
        if body.model not in await ollama.installed_models():
            raise HTTPException(422, 'Model is no longer installed. Refresh models.')
        entries = []
        if requested_scripts:
            if not settings.script_tools_enabled:
                raise HTTPException(403, 'Saved scripts are disabled on this server')
            try:
                entries = await scripts.catalog()
            except Exception as exc:
                raise HTTPException(503, f'Saved-script runner is unavailable: {exc}') from exc
            if not entries:
                raise HTTPException(422, 'No scripts are registered in scripts/tools.json')
            info = await ollama.model_info(body.model)
            if info['supports_tools'] is False:
                raise HTTPException(422, 'Choose a model that supports tool calling to use saved scripts')
        with Session.begin() as db:
            chat = db.get(Chat, chat_id)
            history = history_messages(list(db.scalars(select(Message).where(Message.chat_id == chat_id).order_by(Message.id))))
            # Failed assistant output stays visible but is not sent as context.
            history.append({'role': 'user', 'content': body.content})
            chat.model, chat.updated_at = body.model, now()
            effective_think = body.think
            if 'think' not in body.model_fields_set and chat.assistant_snapshot and chat.reasoning != 'model_default':
                effective_think = chat.reasoning == 'on'
            chat.reasoning = 'model_default' if effective_think is None else 'on' if effective_think else 'off'
            chat.script_tools_enabled = requested_scripts
            system_prompt = assistant_system_prompt(settings.chat_response_style, chat.assistant_snapshot, chat.project_context, bool(entries))
            if not history[:-1]:
                chat.title = body.content.strip()[:60]
            db.add(Message(chat_id=chat_id, role='user', content=body.content, model=body.model))
            assistant = Message(chat_id=chat_id, role='assistant', model=body.model, status='streaming')
            db.add(assistant)
            db.flush()
            assistant_id = assistant.id
    except BaseException as exc:
        active_chats.discard(chat_id)
        if isinstance(exc, HTTPException) or isinstance(exc, asyncio.CancelledError):
            raise
        raise HTTPException(502, f'Ollama preflight failed: {exc}') from exc

    return StreamingResponse(stream_chat(
        chat_id=chat_id, assistant_id=assistant_id, model=body.model, history=history,
        system_prompt=system_prompt, think=effective_think, entries=entries, started=started,
        release=lambda: active_chats.discard(chat_id)),
        media_type='application/x-ndjson', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
