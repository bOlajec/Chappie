import asyncio
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
try:
    from .runner import catalog, execute
except ImportError:
    from runner import catalog, execute

app = FastAPI(title='Saved Python script runner', docs_url=None, redoc_url=None)
gate = asyncio.Lock()


class RunInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    script: str = Field(min_length=1, max_length=48)
    arguments: dict = Field(default_factory=dict)


def root():
    return Path(os.environ.get('SCRIPTS_DIRECTORY', '/scripts'))


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.get('/scripts')
def scripts():
    try:
        return {'scripts': catalog(root())}
    except Exception as exc:
        raise HTTPException(503, f'Script registry is unavailable: {exc}') from exc


@app.post('/run')
async def run(body: RunInput, request: Request):
    if gate.locked():
        raise HTTPException(409, 'Another saved script is running; try again after it finishes')
    async with gate:
        try:
            timeout = max(1, min(120, float(os.environ.get('SCRIPT_TIMEOUT_SECONDS', '30'))))
            limit = max(1024, min(131072, int(os.environ.get('SCRIPT_OUTPUT_BYTES', '32768'))))
            return await execute(root(), body.script, body.arguments, timeout=timeout, output_limit=limit, disconnected=request.is_disconnected)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, f'Script could not be launched: {exc}') from exc
