import asyncio
from urllib.parse import urlsplit
import httpx
from .config import settings


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=httpx.Timeout(settings.ollama_read_timeout, connect=10), trust_env=False)


async def installed_models() -> list[str]:
    async with client() as http:
        response = await http.get('/api/tags', timeout=settings.diagnostic_timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get('models'), list):
            raise ValueError('Invalid Ollama /api/tags response: expected a models list')
        if any(not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or not entry['name'].strip() for entry in data['models']):
            raise ValueError('Invalid Ollama /api/tags response: model name missing')
        return sorted({entry['name'] for entry in data['models']})


async def model_info(model: str) -> dict:
    async with client() as http:
        response = await http.post('/api/show', json={'model': model}, timeout=settings.diagnostic_timeout)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise ValueError('Invalid Ollama /api/show response')
    metadata = data.get('model_info') or {}
    details = data.get('details') or {}
    if not isinstance(metadata, dict) or not isinstance(details, dict):
        raise ValueError('Invalid Ollama model metadata')
    family = details.get('family') or metadata.get('general.architecture')
    finetune = metadata.get('general.finetune', '')
    capabilities = data.get('capabilities')
    return {
        'model': model,
        'supports_thinking': 'thinking' in capabilities if isinstance(capabilities, list) else None,
        'supports_tools': 'tools' in capabilities if isinstance(capabilities, list) else None,
        # The dedicated Qwen3 Thinking weights/template do not reliably honor think=false.
        'thinking_variant': family == 'qwen3' and isinstance(finetune, str) and finetune.casefold() == 'thinking',
    }


async def network_check() -> dict:
    parsed = urlsplit(settings.ollama_base_url)
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)), settings.diagnostic_timeout)
        writer.close()
        await writer.wait_closed()
        return {'status': 'reachable', 'detail': 'TCP connection to configured endpoint succeeded; this does not identify the network route.'}
    except (OSError, asyncio.TimeoutError) as exc:
        return {'status': 'unreachable', 'detail': f'TCP/DNS check failed: {exc}'}


async def ollama_check() -> dict:
    try:
        models = await installed_models()
        return {'status': 'ready', 'detail': f'Ollama /api/tags responded; {len(models)} installed model(s).'}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return {'status': 'unavailable', 'detail': f'Ollama API check failed: {exc}'}


async def diagnostics() -> dict:
    network, ollama = await asyncio.gather(network_check(), ollama_check())
    return {'endpoint': settings.ollama_base_url, 'network': network, 'ollama': ollama,
            'tailscale': {'status': 'unknown', 'detail': 'Tailscale is managed on the host. This container cannot verify host login, peer state, or whether traffic used Tailscale. Run tailscale status and tailscale ping <model-host> on the client host.'}}
