"""Backend bridge to the network-isolated runner over a shared Unix socket."""
import httpx
from .. import config


def client():
    return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=config.settings.script_runner_socket),
        base_url='http://script-runner', timeout=httpx.Timeout(150, connect=3), trust_env=False)


async def catalog():
    async with client() as http:
        response = await http.get('/scripts', timeout=5)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get('scripts'), list):
        raise ValueError('Invalid script catalog response')
    return data['scripts']


def definitions(entries):
    return [{'type': 'function', 'function': {'name': 'saved_' + entry['name'],
        'description': entry['description'], 'parameters': entry['parameters']}} for entry in entries]


async def run(name, arguments):
    async with client() as http:
        response = await http.post('/run', json={'script': name, 'arguments': arguments})
        if response.is_error:
            detail = response.json().get('detail', 'Script runner rejected the request')
            return {'script': name, 'arguments': arguments, 'status': 'rejected', 'exit_code': None,
                    'stdout': '', 'stderr': str(detail)[:1000], 'duration_ms': 0, 'truncated': False}
        response.raise_for_status()
        return response.json()
