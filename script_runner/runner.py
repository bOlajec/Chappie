"""Run registered, owner-supplied Python scripts. Production runs in a separate container."""
import asyncio
import json
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
from time import monotonic
from jsonschema import Draft202012Validator


def catalog(root: Path) -> list[dict]:
    root = root.resolve(strict=True)
    manifest = root / 'tools.json'
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 131072:
        raise ValueError('tools.json must be a regular file under 128 KiB')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    entries = data.get('scripts') if isinstance(data, dict) else None
    if not isinstance(entries, list) or len(entries) > 32:
        raise ValueError('tools.json must contain a scripts list with at most 32 entries')
    result, names = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Every script entry must be an object')
        name, filename = entry.get('name'), entry.get('file')
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', name) or name in names:
            raise ValueError('Script names must be unique lowercase identifiers, at most 48 characters')
        if not isinstance(filename, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*\.py', filename):
            raise ValueError('Only top-level .py filenames are allowed')
        path = root / filename
        if path.is_symlink() or not path.is_file() or path.resolve(strict=True).parent != root:
            raise ValueError(f'Unsafe or missing script: {filename}')
        description, schema = entry.get('description'), entry.get('parameters')
        if not isinstance(description, str) or not description.strip() or len(description) > 1000:
            raise ValueError(f'{name} needs a description of at most 1000 characters')
        if not isinstance(schema, dict) or schema.get('type') != 'object' or schema.get('additionalProperties') is not False:
            raise ValueError(f'{name} parameters must be an object schema with additionalProperties=false')
        def check_refs(value):
            if isinstance(value, dict):
                if any(key in value for key in ('$ref', '$dynamicRef', '$recursiveRef')):
                    raise ValueError('External or recursive schema references are not supported')
                for child in value.values():
                    check_refs(child)
            elif isinstance(value, list):
                for child in value:
                    check_refs(child)
        check_refs(schema)
        Draft202012Validator.check_schema(schema)
        names.add(name)
        result.append({'name': name, 'file': filename, 'description': description, 'parameters': schema})
    return result


def prepare(root: Path, name: str, arguments: dict) -> tuple[Path, bytes]:
    entry = next((entry for entry in catalog(root) if entry['name'] == name), None)
    if not entry:
        raise ValueError('Script is not registered in tools.json')
    payload = json.dumps(arguments, allow_nan=False).encode('utf-8')
    if len(payload) > 16384:
        raise ValueError('Script arguments exceed 16 KiB')
    errors = sorted(Draft202012Validator(entry['parameters']).iter_errors(arguments), key=lambda error: str(error.path))
    if errors:
        raise ValueError('Invalid script arguments: ' + errors[0].message[:500])
    return root.resolve(strict=True) / entry['file'], payload


async def execute(root: Path, name: str, arguments: dict, *, timeout: float = 30, output_limit: int = 32768, disconnected=None) -> dict:
    path, payload = prepare(root, name, arguments)
    started = monotonic()
    stdout, stderr = bytearray(), bytearray()
    total_output = 0
    overflow = asyncio.Event()
    status = 'complete'
    with tempfile.TemporaryDirectory(prefix='saved-script-') as work:
        environment = {'PATH': str(Path(sys.executable).parent) + os.pathsep + os.defpath, 'HOME': work, 'TMPDIR': work,
                       'LANG': 'C.UTF-8', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1'}
        process = await asyncio.create_subprocess_exec(sys.executable, '-I', '-u', '-X', 'utf8', str(path),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=work, env=environment, start_new_session=os.name != 'nt')

        async def collect(reader, destination):
            nonlocal total_output
            while chunk := await reader.read(8192):
                remaining = max(0, output_limit - total_output)
                destination.extend(chunk[:remaining])
                total_output += min(len(chunk), remaining)
                if len(chunk) > remaining:
                    overflow.set()

        async def feed():
            try:
                process.stdin.write(payload)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()

        tasks = [asyncio.create_task(collect(process.stdout, stdout)),
                 asyncio.create_task(collect(process.stderr, stderr)), asyncio.create_task(feed())]
        try:
            while True:
                if overflow.is_set():
                    status = 'output_limit'
                    break
                if process.returncode is not None:
                    break
                if monotonic() - started >= timeout:
                    status = 'timeout'
                    break
                if disconnected is not None and await disconnected():
                    status = 'interrupted'
                    break
                await asyncio.sleep(0.05)
        finally:
            # Also reap ordinary child processes left behind by a completed script.
            if os.name != 'nt':
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.returncode is None:
                process.kill()
            await asyncio.wait_for(process.wait(), timeout=5)
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=3)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
        if overflow.is_set() and status == 'complete':
            status = 'output_limit'
        if status == 'complete' and process.returncode:
            status = 'error'
    return {'script': name, 'arguments': arguments, 'status': status, 'exit_code': process.returncode,
            'stdout': stdout.decode('utf-8', errors='replace'), 'stderr': stderr.decode('utf-8', errors='replace'),
            'duration_ms': round((monotonic() - started) * 1000), 'truncated': overflow.is_set()}
