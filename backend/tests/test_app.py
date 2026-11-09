import importlib
import json
from pathlib import Path
import sys
import pytest
import httpx
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "test.db"}')
    monkeypatch.setenv('OLLAMA_BASE_URL', 'http://model.test:11434')
    monkeypatch.setenv('OLLAMA_KEEP_ALIVE', '10m')
    monkeypatch.setenv('CHAT_RESPONSE_STYLE', 'concise')
    monkeypatch.setenv('SCRIPT_TOOLS_ENABLED', 'false')
    from app import config, db, ollama, main
    importlib.reload(config)
    importlib.reload(db)
    importlib.reload(ollama)
    importlib.reload(main)
    migration = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    command.upgrade(migration, 'head')
    requests = []
    chunks = [{'message': {'content': 'Hello '}, 'done': False}, {'message': {'content': 'world'}, 'done': True}]

    def handler(request):
        requests.append(request)
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': 'tiny:latest'}, {'name': 'other:latest'}]})
        return httpx.Response(200, text='\n'.join(json.dumps(c) for c in chunks))

    monkeypatch.setattr(ollama, 'client', lambda: httpx.AsyncClient(base_url=config.settings.ollama_base_url, transport=httpx.MockTransport(handler)))
    with TestClient(main.app) as client:
        yield client, db, ollama, main, requests, chunks
    db.engine.dispose()


def test_stream_persistence_and_context(setup):
    client, db, _, _, requests, _ = setup
    assert client.get('/api/health').json() == {'status': 'ok'}
    assert client.get('/api/models').json()['models'] == ['other:latest', 'tiny:latest']
    chat = client.post('/api/chats').json()
    response = client.post(f'/api/chats/{chat["id"]}/messages', json={'model': 'tiny:latest', 'content': 'Hi'})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [e['type'] for e in events] == ['start', 'delta', 'delta', 'done']
    saved = client.get(f'/api/chats/{chat["id"]}').json()
    assert saved['title'] == 'Hi'
    assert [(m['role'], m['content'], m['status']) for m in saved['messages']] == [('user', 'Hi', 'complete'), ('assistant', 'Hello world', 'complete')]
    client.post(f'/api/chats/{chat["id"]}/messages', json={'model': 'other:latest', 'content': 'Again'})
    payload = json.loads(requests[-1].content)
    assert payload['model'] == 'other:latest'
    assert payload['messages'][0]['role'] == 'system'
    assert sum(m['role'] == 'system' for m in payload['messages']) == 1
    assert payload['messages'][1:] == [{'role': 'user', 'content': 'Hi'}, {'role': 'assistant', 'content': 'Hello world'}, {'role': 'user', 'content': 'Again'}]
    # A fresh application lifespan and database connection retain history.
    db.engine.dispose()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as reopened:
        assert len(reopened.get(f'/api/chats/{chat["id"]}').json()['messages']) == 4


def test_concise_style_and_opt_out(setup, monkeypatch):
    client, _, _, main, requests, _ = setup
    chat = client.post('/api/chats').json()
    path = f'/api/chats/{chat["id"]}'
    prompt = 'Write a Python edge detector. Output code as text.'
    assert client.post(path + '/messages', json={'model': 'tiny:latest', 'content': prompt}).status_code == 200
    payload = json.loads(requests[-1].content)
    assert [m['role'] for m in payload['messages']] == ['system', 'user']
    assert 'Output only code' in payload['messages'][0]['content']
    assert 'when explicitly requested' in payload['messages'][0]['content']
    assert payload['messages'][1]['content'] == prompt
    assert 'num_predict' not in payload.get('options', {})
    # Application instructions are injected once per request, not persisted as chat turns.
    assert [m['role'] for m in client.get(path).json()['messages']] == ['user', 'assistant']
    monkeypatch.setattr(main.settings, 'chat_response_style', 'model_default')
    client.post(path + '/messages', json={'model': 'tiny:latest', 'content': 'Now explain the code in detail.'})
    payload = json.loads(requests[-1].content)
    assert [m['role'] for m in payload['messages']] == ['user', 'assistant', 'user']


@pytest.mark.parametrize('ending', ['eof', 'error', 'malformed'])
def test_failed_stream_retains_partial_output(setup, ending):
    client, _, _, _, _, chunks = setup
    chunks[:] = [{'message': {'content': 'Partial'}, 'done': False}]
    if ending == 'error':
        chunks.append({'error': 'Model ran out of memory'})
    if ending == 'malformed':
        chunks.append({'message': {'content': 123}})
    chat = client.post('/api/chats').json()
    response = client.post(f'/api/chats/{chat["id"]}/messages', json={'model': 'tiny:latest', 'content': 'Hi'})
    assert json.loads(response.text.splitlines()[-1])['type'] == 'error'
    saved = client.get(f'/api/chats/{chat["id"]}').json()['messages'][-1]
    assert (saved['content'], saved['status']) == ('Partial', 'error')


def test_reasoning_control_and_timing_metadata(setup):
    client, _, _, _, requests, chunks = setup
    chunks[:] = [
        {'message': {'thinking': 'internal reasoning'}, 'done': False},
        {'message': {'content': 'Hello'}, 'done': False},
        {'done': True, 'load_duration': 200_000_000, 'prompt_eval_duration': 100_000_000,
         'eval_duration': 2_000_000_000, 'eval_count': 20},
    ]
    chat = client.post('/api/chats').json()
    path = f'/api/chats/{chat["id"]}/messages'
    response = client.post(path, json={'model': 'tiny:latest', 'content': 'Hello', 'think': False})
    payload = json.loads(requests[-1].content)
    assert payload['think'] is False
    assert payload['keep_alive'] == '10m'
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [e['type'] for e in events] == ['start', 'status', 'delta', 'done']
    assert 'internal reasoning' not in response.text
    timing = events[-1]['timings']
    assert timing['load_ms'] == 200
    assert timing['prompt_ms'] == 100
    assert timing['generation_ms'] == 2000
    assert timing['tokens_per_second'] == 10
    assert 0 <= timing['first_chunk_ms'] <= timing['first_text_ms'] <= timing['total_ms']
    client.post(path, json={'model': 'tiny:latest', 'content': 'Again', 'think': True})
    assert json.loads(requests[-1].content)['think'] is True
    client.post(path, json={'model': 'tiny:latest', 'content': 'Default'})
    assert 'think' not in json.loads(requests[-1].content)


def test_fast_stream_batches_database_checkpoints(setup, monkeypatch):
    client, db, _, _, _, chunks = setup
    from sqlalchemy import event
    # Hold the clock fixed to simulate tokens arriving inside one checkpoint interval.
    monkeypatch.setattr('app.main.monotonic', lambda: 100.0)
    monkeypatch.setattr('app.chat_stream.monotonic', lambda: 100.0)
    chunks[:] = [{'message': {'content': 'x'}, 'done': False} for _ in range(100)] + [{'done': True}]
    updates = []
    def record(connection, cursor, statement, parameters, context, many):
        if statement.startswith('UPDATE messages'):
            updates.append(statement)
    event.listen(db.engine, 'before_cursor_execute', record)
    try:
        chat = client.post('/api/chats').json()
        response = client.post(f'/api/chats/{chat["id"]}/messages', json={'model': 'tiny:latest', 'content': 'Hi'})
        assert len([line for line in response.text.splitlines() if json.loads(line)['type'] == 'delta']) == 100
        assert len(updates) <= 2
        saved = client.get(f'/api/chats/{chat["id"]}').json()['messages'][-1]
        assert saved['content'] == 'x' * 100
        assert saved['status'] == 'complete'
    finally:
        event.remove(db.engine, 'before_cursor_execute', record)


def test_validation_and_busy_chat(setup):
    client, _, _, main, _, _ = setup
    chat = client.post('/api/chats').json()
    path = f'/api/chats/{chat["id"]}/messages'
    assert client.get('/api/chats/missing').status_code == 404
    assert client.post('/api/chats/missing/messages', json={'content': 'hi', 'model': 'tiny:latest'}).status_code == 404
    for content, model in [(' ', 'tiny:latest'), ('hi', 'missing'), ('', 'tiny:latest')]:
        assert client.post(path, json={'content': content, 'model': model}).status_code == 422
    assert client.get(f'/api/chats/{chat["id"]}').json()['messages'] == []
    main.active_chats.add(chat['id'])
    assert client.post(path, json={'content': 'hi', 'model': 'tiny:latest'}).status_code == 409


def test_ollama_failure_does_not_claim_tailscale_disconnected(setup, monkeypatch):
    client, _, ollama, _, _, _ = setup
    async def network():
        return {'status': 'reachable', 'detail': 'TCP works'}
    def failed(request):
        return httpx.Response(503)
    monkeypatch.setattr(ollama, 'network_check', network)
    monkeypatch.setattr(ollama, 'client', lambda: httpx.AsyncClient(base_url='http://model.test', transport=httpx.MockTransport(failed)))
    result = client.get('/api/diagnostics').json()
    assert result['network']['status'] == 'reachable'
    assert result['ollama']['status'] == 'unavailable'
    assert result['tailscale']['status'] == 'unknown'
    assert client.get('/api/models').status_code == 502
    chat = client.post('/api/chats').json()
    assert client.post(f'/api/chats/{chat["id"]}/messages', json={'content': 'hi', 'model': 'tiny:latest'}).status_code == 502
    assert client.get(f'/api/chats/{chat["id"]}').json()['messages'] == []


def test_restart_marks_unfinished_message_interrupted(setup):
    client, db, _, main, _, _ = setup
    chat = client.post('/api/chats').json()
    with db.Session.begin() as session:
        session.add(db.Message(chat_id=chat['id'], role='assistant', content='unfinished', model='tiny:latest', status='streaming'))
    with TestClient(main.app) as restarted:
        assert restarted.get(f'/api/chats/{chat["id"]}').json()['messages'][0]['status'] == 'interrupted'


@pytest.mark.parametrize('payload', [[], {}, {'models': 'wrong'}, {'models': [42]}, {'models': [{'name': ''}]}])
def test_invalid_model_response_keeps_diagnostics_available(setup, monkeypatch, payload):
    client, _, ollama, _, _, _ = setup
    async def network():
        return {'status': 'reachable', 'detail': 'TCP works'}
    monkeypatch.setattr(ollama, 'network_check', network)
    monkeypatch.setattr(ollama, 'client', lambda: httpx.AsyncClient(base_url='http://model.test', transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))))
    result = client.get('/api/diagnostics')
    assert result.status_code == 200
    assert result.json()['network']['status'] == 'reachable'
    assert result.json()['ollama']['status'] == 'unavailable'
    assert client.get('/api/models').status_code == 502


@pytest.mark.parametrize('family,finetune,capabilities,thinking_variant,supports_thinking', [
    ('qwen3', 'Thinking', ['completion', 'thinking'], True, True),
    ('qwen3', '', ['completion', 'thinking'], False, True),
    ('qwen3', 'Instruct', ['completion'], False, False),
    ('qwen3_5', '', ['completion', 'thinking'], False, True),
    ('unknown', '', None, False, None),
])
def test_selected_model_capabilities(setup, monkeypatch, family, finetune, capabilities, thinking_variant, supports_thinking):
    client, _, ollama, _, _, _ = setup
    def show(request):
        assert request.url.path == '/api/show'
        assert json.loads(request.content)['model'] == 'namespace/test:latest'
        return httpx.Response(200, json={'details': {'family': family},
            'model_info': {'general.finetune': finetune}, 'capabilities': capabilities})
    monkeypatch.setattr(ollama, 'client', lambda: httpx.AsyncClient(base_url='http://model.test', transport=httpx.MockTransport(show)))
    response = client.get('/api/model-info', params={'model': 'namespace/test:latest'})
    assert response.status_code == 200
    assert response.json() == {'model': 'namespace/test:latest', 'thinking_variant': thinking_variant,
        'supports_thinking': supports_thinking, 'supports_tools': 'tools' in capabilities if capabilities is not None else None}


def test_selected_model_info_unavailable(setup, monkeypatch):
    client, _, ollama, _, _, _ = setup
    monkeypatch.setattr(ollama, 'client', lambda: httpx.AsyncClient(base_url='http://model.test', transport=httpx.MockTransport(lambda _: httpx.Response(404))))
    assert client.get('/api/model-info', params={'model': 'missing'}).status_code == 502
    assert client.get('/api/model-info', params={'model': ''}).status_code == 422


def test_migration_downgrade_upgrade(setup):
    _, db, _, _, _, _ = setup
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    command.downgrade(config, 'base')
    command.upgrade(config, 'head')
    with db.Session() as session:
        assert session.query(db.Chat).count() == 0


def test_profile_crud_and_no_model_dependency(setup):
    client, _, _, _, requests, _ = setup
    starter = client.get('/api/assistants').json()
    assert starter[0]['name'] == 'Arduino Developer'
    assert starter[0]['preferred_model'] == ''
    assert 'no compiler' in starter[0]['instructions']
    profile = client.post('/api/assistants', json={'name': '  Sensor helper  ', 'instructions': 'Use the supplied board.', 'preferred_model': 'not-installed:latest'}).json()
    assert profile['name'] == 'Sensor helper'
    changed = client.put(f'/api/assistants/{profile["id"]}', json={'name': 'Sensor helper v2', 'reasoning': 'on', 'reference_notes': 'API example'}).json()
    assert changed['id'] == profile['id']
    assert changed['reasoning'] == 'on'
    assert changed['reference_notes'] == 'API example'
    assert not requests, 'Editing profiles should work without contacting Ollama'
    assert client.delete(f'/api/assistants/{profile["id"]}').status_code == 204
    assert client.delete(f'/api/assistants/{profile["id"]}').status_code == 404


@pytest.mark.parametrize('payload', [
    {'name': '   '}, {'name': 'x' * 81}, {'name': 'test', 'reasoning': 'high'},
    {'name': 'test', 'instructions': 'x' * 12001},
    {'name': 'test', 'project_context': 'x' * 12001},
    {'name': 'test', 'reference_notes': 'x' * 24001},
    {'name': 'test', 'tools': ['compile']},
])
def test_profile_validation(setup, payload):
    client, _, _, _, _, _ = setup
    assert client.post('/api/assistants', json=payload).status_code == 422


def test_profile_snapshot_context_and_reasoning(setup):
    client, _, _, _, requests, _ = setup
    profile = client.post('/api/assistants', json={'name': 'Arduino pins', 'instructions': 'Ask before changing pin assignments.',
        'project_context': 'Board: Uno; LED: pin 7', 'reference_notes': 'Sensor docs example',
        'preferred_model': 'other:latest', 'reasoning': 'off'}).json()
    chat = client.post('/api/chats', json={'assistant_id': profile['id'], 'project_context': 'Board: Nano; LED: pin 4'}).json()
    path = f'/api/chats/{chat["id"]}'
    assert chat['model'] == 'other:latest'
    assert chat['reasoning'] == 'off'
    assert chat['assistant_name'] == 'Arduino pins'
    assert chat['assistant_snapshot']['reference_notes'] == 'Sensor docs example'
    assert client.get('/api/chats').json()[0]['assistant_name'] == 'Arduino pins'
    assert 'assistant_snapshot' not in client.get('/api/chats').json()[0]
    client.post(path + '/messages', json={'model': 'other:latest', 'content': 'Blink the LED'})
    payload = json.loads(requests[-1].content)
    system = payload['messages'][0]['content']
    assert [m['role'] for m in payload['messages']] == ['system', 'user']
    assert system.count('Ask before changing pin assignments.') == 1
    assert 'Board: Nano; LED: pin 4' in system
    assert 'Board: Uno; LED: pin 7' not in system
    assert 'Sensor docs example' in system
    assert payload['think'] is False
    assert 'tools' not in payload
    assert [m['role'] for m in client.get(path).json()['messages']] == ['user', 'assistant']
    client.post(path + '/messages', json={'model': 'tiny:latest', 'content': 'Use default reasoning', 'think': None})
    assert 'think' not in json.loads(requests[-1].content)
    saved = client.get(path).json()
    assert saved['reasoning'] == 'model_default'
    assert saved['model'] == 'tiny:latest'
    client.patch(path + '/context', json={'project_context': 'Board: Nano; LED: pin 6'})
    client.post(path + '/messages', json={'model': 'tiny:latest', 'content': 'Now what?'})
    assert 'LED: pin 6' in json.loads(requests[-1].content)['messages'][0]['content']
    other = client.post('/api/chats', json={'assistant_id': profile['id']}).json()
    assert other['project_context'] == 'Board: Uno; LED: pin 7'
    general = client.post('/api/chats').json()
    client.post(f'/api/chats/{general["id"]}/messages', json={'model': 'tiny:latest', 'content': 'A separate conversation'})
    unrelated_prompt = json.loads(requests[-1].content)['messages'][0]['content']
    assert 'Sensor docs example' not in unrelated_prompt
    assert 'LED: pin 6' not in unrelated_prompt


def test_profile_edits_deletion_and_chat_refresh_preserve_history(setup):
    client, db, _, main, requests, _ = setup
    profile = client.post('/api/assistants', json={'name': 'Original', 'instructions': 'Original guidance'}).json()
    chat = client.post('/api/chats', json={'assistant_id': profile['id']}).json()
    path = f'/api/chats/{chat["id"]}'
    client.post(path + '/messages', json={'model': 'tiny:latest', 'content': 'hello'})
    client.put(f'/api/assistants/{profile["id"]}', json={'name': 'Updated', 'instructions': 'Updated guidance'})
    saved = client.get(path).json()
    assert saved['assistant_name'] == 'Original'
    assert saved['assistant_snapshot']['instructions'] == 'Original guidance'
    updated = client.patch(path + '/assistant', json={'assistant_id': profile['id'], 'project_context': 'Keep my wiring'}).json()
    assert updated['assistant_name'] == 'Updated'
    assert len(client.get(path).json()['messages']) == 2
    client.delete(f'/api/assistants/{profile["id"]}')
    db.engine.dispose()
    with TestClient(main.app) as reopened:
        saved = reopened.get(path).json()
        assert saved['assistant_id'] is None
        assert saved['assistant_snapshot']['instructions'] == 'Updated guidance'
        assert saved['project_context'] == 'Keep my wiring'
        reopened.post(path + '/messages', json={'model': 'tiny:latest', 'content': 'Continue'})
        assert 'Updated guidance' in json.loads(requests[-1].content)['messages'][0]['content']
    general = client.patch(path + '/assistant', json={'assistant_id': None}).json()
    assert general['assistant_snapshot'] is None
    assert general['project_context'] == ''
    assert len(client.get(path).json()['messages']) == 4


def test_invalid_and_busy_chat_profile_changes(setup):
    client, _, _, main, _, _ = setup
    assert client.post('/api/chats', json={'assistant_id': 'missing'}).status_code == 404
    chat = client.post('/api/chats').json()
    path = f'/api/chats/{chat["id"]}'
    assert client.patch(path + '/assistant', json={'assistant_id': 'missing'}).status_code == 404
    assert client.patch(path + '/context', json={'project_context': 'x' * 12001}).status_code == 422
    assert client.patch('/api/chats/missing/context', json={'project_context': ''}).status_code == 404
    main.active_chats.add(chat['id'])
    assert client.patch(path + '/assistant', json={'assistant_id': None}).status_code == 409
    assert client.patch(path + '/context', json={'project_context': 'cannot change'}).status_code == 409


def test_upgrade_preserves_pre_profile_chats_and_messages(setup):
    client, db, _, _, _, _ = setup
    from sqlalchemy import text
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    command.downgrade(config, '0001')
    with db.engine.begin() as connection:
        connection.execute(text("INSERT INTO chats (id,title,model,updated_at) VALUES ('legacy','Old chat','tiny:latest','2026-11-01')"))
        connection.execute(text("INSERT INTO messages (chat_id,role,content,model,status,created_at) VALUES ('legacy','user','Keep this history','tiny:latest','complete','2026-11-01')"))
    command.upgrade(config, 'head')
    saved = client.get('/api/chats/legacy').json()
    assert saved['assistant_snapshot'] is None
    assert saved['project_context'] == ''
    assert saved['messages'][0]['content'] == 'Keep this history'
    assert len(client.get('/api/assistants').json()) == 1


@pytest.fixture
def script_tools(setup, monkeypatch):
    client, db, ollama, main, requests, _ = setup
    from app.tools import scripts
    monkeypatch.setattr(main.settings, 'script_tools_enabled', True)
    entries = [{'name': 'add_numbers', 'file': 'add_numbers.py', 'description': 'Sum numbers',
        'parameters': {'type': 'object', 'properties': {'numbers': {'type': 'array', 'items': {'type': 'number'}}},
                       'required': ['numbers'], 'additionalProperties': False}}]
    executions = []
    state = {'name': 'saved_add_numbers', 'arguments': {'numbers': [2, 3]}, 'repeat': False,
             'force': False, 'supports_tools': True, 'result_status': 'complete', 'multiple': False}
    async def catalog():
        return entries
    async def run(name, arguments):
        executions.append((name, arguments))
        return {'script': name, 'arguments': arguments, 'status': state['result_status'],
                'exit_code': 0 if state['result_status'] == 'complete' else 2,
                'stdout': '{"sum":5}' if state['result_status'] == 'complete' else '',
                'stderr': '' if state['result_status'] == 'complete' else 'Script failed',
                'duration_ms': 20, 'truncated': False}
    monkeypatch.setattr(scripts, 'catalog', catalog)
    monkeypatch.setattr(scripts, 'run', run)
    def handler(request):
        requests.append(request)
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': 'tiny:latest'}]})
        if request.url.path == '/api/show':
            return httpx.Response(200, json={'capabilities': ['completion', 'tools'] if state['supports_tools'] else ['completion']})
        payload = json.loads(request.content)
        if state['repeat'] or state['force'] or (payload.get('tools') and payload['messages'][-1]['role'] == 'user'):
            call = {'type': 'function', 'function': {'name': state['name'], 'arguments': state['arguments']}}
            calls = [call, call] if state['multiple'] else [call]
            chunks = [{'message': {'tool_calls': calls}, 'done': False}, {'done': True}]
        else:
            chunks = [{'message': {'content': 'The script result is available.'}, 'done': True}]
        return httpx.Response(200, text='\n'.join(json.dumps(chunk) for chunk in chunks))
    monkeypatch.setattr(ollama, 'client', lambda: httpx.AsyncClient(base_url='http://model.test', transport=httpx.MockTransport(handler)))
    return client, db, main, requests, executions, state


def test_model_script_loop_persists_results_and_replays_history(script_tools):
    client, _, _, requests, executions, _ = script_tools
    chat = client.post('/api/chats').json()
    path = f'/api/chats/{chat["id"]}'
    response = client.post(path + '/messages', json={'model': 'tiny:latest', 'content': 'Sum 2 and 3', 'use_scripts': True})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [e['type'] for e in events] == ['start', 'tool_calls', 'tool_start', 'tool_result', 'assistant_start', 'delta', 'done']
    assert executions == [('add_numbers', {'numbers': [2, 3]})]
    model_request = json.loads(requests[-1].content)
    assert [m['role'] for m in model_request['messages']] == ['system', 'user', 'assistant', 'tool']
    assert json.loads(model_request['messages'][-1]['content'])['stdout'] == '{"sum":5}'
    saved = client.get(path).json()
    assert saved['script_tools_enabled'] is True
    assert [m['role'] for m in saved['messages']] == ['user', 'assistant', 'tool', 'assistant']
    assert saved['messages'][1]['tool_calls'][0]['function']['name'] == 'saved_add_numbers'
    assert saved['messages'][2]['tool_name'] == 'saved_add_numbers'
    client.post(path + '/messages', json={'model': 'tiny:latest', 'content': 'Continue without tools', 'use_scripts': False})
    payload = json.loads(requests[-1].content)
    assert 'tools' not in payload
    assert [m['role'] for m in payload['messages']] == ['system', 'user', 'assistant', 'tool', 'assistant', 'user']
    assert len(executions) == 1


def test_unrequested_and_unknown_tools_never_execute(script_tools):
    client, _, _, _, executions, state = script_tools
    chat = client.post('/api/chats').json()
    path = f'/api/chats/{chat["id"]}/messages'
    state['force'] = True
    response = client.post(path, json={'model': 'tiny:latest', 'content': 'Hi', 'use_scripts': False})
    assert json.loads(response.text.splitlines()[-1])['type'] == 'error'
    assert not executions
    state.update(force=False, name='saved_unregistered')
    response = client.post(path, json={'model': 'tiny:latest', 'content': 'Try a tool', 'use_scripts': True})
    results = [json.loads(line) for line in response.text.splitlines() if json.loads(line)['type'] == 'tool_result']
    assert json.loads(results[0]['message']['content'])['status'] == 'rejected'
    assert not executions


def test_runner_failure_and_model_capability_fail_before_saving_input(script_tools, monkeypatch):
    client, _, _, _, _, state = script_tools
    from app.tools import scripts
    chat = client.post('/api/chats').json()
    path = f'/api/chats/{chat["id"]}'
    state['supports_tools'] = False
    assert client.post(path + '/messages', json={'model': 'tiny:latest', 'content': 'Hi', 'use_scripts': True}).status_code == 422
    async def unavailable():
        raise RuntimeError('Runner offline')
    monkeypatch.setattr(scripts, 'catalog', unavailable)
    assert client.get('/api/scripts').json()['available'] is False
    assert client.post(path + '/messages', json={'model': 'tiny:latest', 'content': 'Hi', 'use_scripts': True}).status_code == 503
    assert client.get(path).json()['messages'] == []
    assert client.post(path + '/messages', json={'model': 'tiny:latest', 'content': 'Hi', 'use_scripts': False}).status_code == 200


def test_multiple_tool_calls_errors_and_call_budget(script_tools, monkeypatch):
    client, _, main, _, executions, state = script_tools
    chat = client.post('/api/chats').json()
    path = f'/api/chats/{chat["id"]}'
    state.update(multiple=True, result_status='error')
    response = client.post(path + '/messages', json={'model': 'tiny:latest', 'content': 'Run tools', 'use_scripts': True})
    assert json.loads(response.text.splitlines()[-1])['type'] == 'done'
    assert len(executions) == 2
    saved = client.get(path).json()
    assert [m['role'] for m in saved['messages']] == ['user', 'assistant', 'tool', 'tool', 'assistant']
    assert json.loads(saved['messages'][2]['content'])['status'] == 'error'
    state.update(multiple=False, repeat=True, result_status='complete')
    monkeypatch.setattr(main.settings, 'script_max_calls', 1)
    response = client.post(path + '/messages', json={'model': 'tiny:latest', 'content': 'Again', 'use_scripts': True})
    assert json.loads(response.text.splitlines()[-1])['type'] == 'error'
    assert len(executions) == 3, 'The model must not bypass the per-message execution limit'


def test_profile_script_preference_and_explicit_off_override(script_tools):
    client, _, _, _, executions, _ = script_tools
    profile = client.post('/api/assistants', json={'name': 'Script helper', 'script_tools_enabled': True}).json()
    chat = client.post('/api/chats', json={'assistant_id': profile['id']}).json()
    assert chat['script_tools_enabled'] is True
    path = f'/api/chats/{chat["id"]}'
    client.post(path + '/messages', json={'model': 'tiny:latest', 'content': 'Use the profile tool preference'})
    assert len(executions) == 1
    client.post(path + '/messages', json={'model': 'tiny:latest', 'content': 'No tools now', 'use_scripts': False})
    assert len(executions) == 1
    assert client.get(path).json()['script_tools_enabled'] is False


def test_interrupted_tool_exchange_excluded_from_context(script_tools):
    client, db, _, requests, _, _ = script_tools
    chat = client.post('/api/chats').json()
    with db.Session.begin() as session:
        session.add(db.Message(chat_id=chat['id'], role='assistant', status='complete', content='', tool_calls=[{'type':'function','function':{'name':'saved_add_numbers','arguments':{'numbers':[2,3]}}}]))
        session.add(db.Message(chat_id=chat['id'], role='tool', status='interrupted', tool_name='saved_add_numbers', content='incomplete result'))
    client.post(f'/api/chats/{chat["id"]}/messages', json={'model':'tiny:latest','content':'Hello','use_scripts':False})
    assert [m['role'] for m in json.loads(requests[-1].content)['messages']] == ['system','user']


def test_tool_request_cancellation_saves_interrupted_activity(script_tools, monkeypatch):
    client, db, _, _, _, _ = script_tools
    import asyncio
    from time import monotonic
    from app.chat_stream import stream_chat
    from app.tools import scripts
    cancelled = []
    async def waiting(name, arguments):
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.append(True)
    monkeypatch.setattr(scripts, 'run', waiting)
    chat = client.post('/api/chats').json()
    with db.Session.begin() as session:
        assistant = db.Message(chat_id=chat['id'],role='assistant',model='tiny:latest',status='streaming')
        session.add(assistant)
        session.flush()
        assistant_id = assistant.id
    released = []
    async def cancel():
        entries = await scripts.catalog()
        stream = stream_chat(chat_id=chat['id'],assistant_id=assistant_id,model='tiny:latest',
            history=[{'role':'user','content':'Run script'}],system_prompt='',think=False,entries=entries,
            started=monotonic(),release=lambda:released.append(True))
        assert json.loads(await anext(stream))['type']=='start'
        assert json.loads(await anext(stream))['type']=='tool_calls'
        assert json.loads(await anext(stream))['type']=='tool_start'
        task = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(cancel())
    assert cancelled and released
    saved = client.get(f'/api/chats/{chat["id"]}').json()['messages']
    assert saved[-1]['role']=='tool'
    assert saved[-1]['status']=='interrupted'
    assert json.loads(saved[-1]['content'])['status']=='interrupted'
