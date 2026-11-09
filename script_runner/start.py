import os
from pathlib import Path
import uvicorn

socket = Path('/run/script-runner/runner.sock')
if socket.exists():
    socket.unlink()
os.umask(0o077)
uvicorn.run('app:app', uds=str(socket), workers=1, access_log=False)
