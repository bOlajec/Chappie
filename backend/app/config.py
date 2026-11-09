from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import urlsplit
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    ollama_base_url: str = 'http://host.docker.internal:11434'
    database_url: str = 'sqlite:///./data/chats.db'
    ollama_read_timeout: float = Field(default=180, gt=0)
    diagnostic_timeout: float = Field(default=5, gt=0)
    ollama_keep_alive: str = '10m'
    chat_response_style: Literal['concise', 'model_default'] = 'concise'
    script_tools_enabled: bool = False
    script_runner_socket: str = '/run/script-runner/runner.sock'
    script_max_calls: int = Field(default=4, ge=1, le=8)

    @field_validator('ollama_base_url')
    @classmethod
    def valid_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError('Use an http(s) origin without credentials, path, query or fragment')
        return value.rstrip('/')


settings = Settings()
