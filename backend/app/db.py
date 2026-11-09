from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, ForeignKey, JSON, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class Chat(Base):
    __tablename__ = 'chats'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String, default='New chat')
    model: Mapped[str] = mapped_column(String, default='')
    updated_at: Mapped[str] = mapped_column(String, default=now)
    assistant_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    assistant_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    project_context: Mapped[str] = mapped_column(Text, default='')
    reasoning: Mapped[str] = mapped_column(String, default='off')
    script_tools_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class AssistantProfile(Base):
    __tablename__ = 'assistant_profiles'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String, default='')
    instructions: Mapped[str] = mapped_column(Text, default='')
    project_context: Mapped[str] = mapped_column(Text, default='')
    reference_notes: Mapped[str] = mapped_column(Text, default='')
    preferred_model: Mapped[str] = mapped_column(String, default='')
    reasoning: Mapped[str] = mapped_column(String, default='off')
    updated_at: Mapped[str] = mapped_column(String, default=now)
    script_tools_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class Message(Base):
    __tablename__ = 'messages'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey('chats.id'), index=True)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text, default='')
    model: Mapped[str] = mapped_column(String, default='')
    status: Mapped[str] = mapped_column(String, default='complete')
    created_at: Mapped[str] = mapped_column(String, default=now)
    tool_calls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tool_name: Mapped[str] = mapped_column(String, default='')


engine = create_engine(settings.database_url, connect_args={'check_same_thread': False, 'timeout': 15})


@event.listens_for(engine, 'connect')
def sqlite_options(connection, _):
    connection.execute('PRAGMA foreign_keys=ON')
    connection.execute('PRAGMA journal_mode=WAL')


Session = sessionmaker(engine, expire_on_commit=False)
