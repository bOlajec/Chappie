"""Exercise real HTTP streaming and disconnect cleanup, without a real model."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import httpx


def test_live_stream_and_disconnect(tmp_path):
    class FakeOllama(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"models":[{"name":"test:latest"}]}')

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-ndjson')
            self.end_headers()
            try:
                for content, done in [('First ', False), ('second', False), ('', True)]:
                    self.wfile.write((json.dumps({'message': {'content': content}, 'done': done}) + '\n').encode())
                    self.wfile.flush()
                    time.sleep(0.6)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    backend = Path(__file__).resolve().parents[1]
    fake = ThreadingHTTPServer(('127.0.0.1', 0), FakeOllama)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{tmp_path / "live.db"}', 'OLLAMA_BASE_URL': f'http://127.0.0.1:{fake.server_port}'}
    process = None
    try:
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=backend, env=env, check=True, capture_output=True)
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)], cwd=backend, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=5) as client:
            deadline = time.monotonic() + 15
            while True:
                try:
                    if client.get('/api/health').status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert process.poll() is None, 'Backend exited before becoming healthy'
                assert time.monotonic() < deadline, 'Backend startup timed out'
                time.sleep(0.1)
            checks = client.get('/api/diagnostics').json()
            assert checks['network']['status'] == 'reachable'
            assert checks['ollama']['status'] == 'ready'
            assert checks['tailscale']['status'] == 'unknown'
            chat_id = client.post('/api/chats').json()['id']
            path = f'/api/chats/{chat_id}'
            with client.stream('POST', path + '/messages', json={'model': 'test:latest', 'content': 'Hello'}) as response:
                lines = response.iter_lines()
                assert json.loads(next(lines))['type'] == 'start'
                started = time.monotonic()
                assert json.loads(next(lines))['content'] == 'First '
                assert time.monotonic() - started < 1, 'First chunk was buffered'
                remaining = [json.loads(line) for line in lines]
                assert remaining[-1]['type'] == 'done'
            assert client.get(path).json()['messages'][-1]['content'] == 'First second'
            with client.stream('POST', path + '/messages', json={'model': 'test:latest', 'content': 'Stop me'}) as response:
                lines = response.iter_lines()
                assert json.loads(next(lines))['type'] == 'start'
                assert json.loads(next(lines))['content'] == 'First '
                # Closing the connection before the final chunk must cancel generation.
            deadline = time.monotonic() + 5
            while True:
                message = client.get(path).json()['messages'][-1]
                if message['status'] != 'streaming':
                    break
                assert time.monotonic() < deadline, 'Disconnected stream did not finalize'
                time.sleep(0.1)
            assert message['status'] == 'interrupted'
            assert message['content'].startswith('First ')
    finally:
        if process:
            process.terminate()
            process.wait(timeout=10)
        fake.shutdown()
        fake.server_close()
