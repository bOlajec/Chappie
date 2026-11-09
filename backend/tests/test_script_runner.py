import asyncio
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from script_runner.runner import catalog, execute, prepare


@pytest.fixture
def script_folder(tmp_path):
    (tmp_path / 'test.py').write_text('import json,sys\ndata=json.load(sys.stdin)\nprint(json.dumps(data))\n', encoding='utf-8')
    manifest = {'scripts': [{'name': 'test', 'file': 'test.py', 'description': 'Test script',
        'parameters': {'type': 'object', 'properties': {'text': {'type': 'string', 'maxLength': 4000}},
                       'required': ['text'], 'additionalProperties': False}}]}
    (tmp_path / 'tools.json').write_text(json.dumps(manifest), encoding='utf-8')
    return tmp_path, manifest


def test_script_arguments_are_data_not_shell_code(script_folder):
    root, _ = script_folder
    value = 'hello; $(echo should-not-run) & python -c pass ☃'
    result = asyncio.run(execute(root, 'test', {'text': value}))
    assert result['status'] == 'complete'
    assert result['exit_code'] == 0
    assert json.loads(result['stdout']) == {'text': value}
    assert not result['truncated']


@pytest.mark.parametrize('filename', ['../outside.py', '/tmp/test.py', 'sub/test.py', 'test.py;echo', 'C:\\test.py', '-c.py'])
def test_registry_rejects_unsafe_filenames(script_folder, filename):
    root, manifest = script_folder
    manifest['scripts'][0]['file'] = filename
    (root / 'tools.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        catalog(root)


@pytest.mark.parametrize('arguments', [{}, {'text': 3}, {'text': 'okay', 'code': 'print(1)'}, {'text': 'x' * 4001}])
def test_arguments_must_match_registered_schema(script_folder, arguments):
    root, _ = script_folder
    with pytest.raises(ValueError, match='Invalid script arguments'):
        prepare(root, 'test', arguments)


def test_unregistered_scripts_and_external_schema_references_rejected(script_folder):
    root, manifest = script_folder
    with pytest.raises(ValueError, match='not registered'):
        prepare(root, '../../anything.py', {'text': 'x'})
    manifest['scripts'][0]['parameters']['properties']['text'] = {'$ref': 'https://example.com/schema'}
    (root / 'tools.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='references'):
        catalog(root)


def test_symlink_script_rejected(script_folder):
    root, _ = script_folder
    real = root / 'real.py'
    (root / 'test.py').rename(real)
    try:
        (root / 'test.py').symlink_to(real)
    except OSError:
        pytest.skip('Creating symlinks is not permitted on this Windows installation')
    with pytest.raises(ValueError, match='Unsafe'):
        catalog(root)


def test_timeout_output_limit_and_script_failure(script_folder):
    root, _ = script_folder
    (root / 'test.py').write_text('import time\nprint("partial",flush=True)\ntime.sleep(10)\n')
    result = asyncio.run(execute(root, 'test', {'text': 'x'}, timeout=0.3))
    assert result['status'] == 'timeout'
    assert 'partial' in result['stdout']
    assert result['duration_ms'] < 5000
    (root / 'test.py').write_text('print("x"*100000)\n')
    result = asyncio.run(execute(root, 'test', {'text': 'x'}, output_limit=1024))
    assert result['status'] == 'output_limit'
    assert result['truncated']
    assert len(result['stdout'].encode()) + len(result['stderr'].encode()) <= 1024
    (root / 'test.py').write_text('import sys\nprint("failure",file=sys.stderr)\nsys.exit(7)\n')
    result = asyncio.run(execute(root, 'test', {'text': 'x'}))
    assert result['status'] == 'error'
    assert result['exit_code'] == 7
    assert 'failure' in result['stderr']


def test_temporary_working_directory_and_clean_environment(script_folder, monkeypatch):
    root, _ = script_folder
    monkeypatch.setenv('TEST_PRIVATE_SECRET', 'must-not-be-visible')
    (root / 'test.py').write_text('import os,json\nfrom pathlib import Path\nPath("scratch.txt").write_text("temporary")\nprint(json.dumps({"cwd":os.getcwd(),"secret":os.getenv("TEST_PRIVATE_SECRET")}))\n')
    result = asyncio.run(execute(root, 'test', {'text': 'x'}))
    data = json.loads(result['stdout'])
    assert data['secret'] is None
    assert not Path(data['cwd']).exists()
    assert not (root / 'scratch.txt').exists()


def test_disconnect_and_cancellation_reap_process(script_folder):
    root, _ = script_folder
    (root / 'test.py').write_text('import time\nprint("started",flush=True)\ntime.sleep(10)\n')
    async def disconnected():
        return True
    result = asyncio.run(execute(root, 'test', {'text': 'x'}, disconnected=disconnected))
    assert result['status'] == 'interrupted'
    assert result['duration_ms'] < 3000
    async def cancel():
        task = asyncio.create_task(execute(root, 'test', {'text': 'x'}))
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(cancel())
