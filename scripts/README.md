# Saved Python scripts

Put trusted, self-contained `.py` files in this folder and register them in `tools.json`. Files alone are not executable by the model until registered. Only top-level Python filenames are supported; no paths, symlinks, shell scripts, executable strings, or arbitrary commands are accepted.

Two examples are included:

- `add_numbers`: accepts `{"numbers": [2, 3]}` and returns `{"sum": 5.0}`.
- `text_stats`: accepts `{"text": "hello world"}` and returns word, character and line counts.

Each tool entry supplies:

```json
{
  "name": "example",
  "file": "example.py",
  "description": "Describe when the model should use this script.",
  "parameters": {
    "type": "object",
    "properties": {"text": {"type": "string", "maxLength": 4000}},
    "required": ["text"],
    "additionalProperties": false
  }
}
```

Add entries to the existing `scripts` array rather than replacing it. Names must be unique lowercase identifiers (letters, digits and underscores), starting with a letter, at most 48 characters. Descriptions are limited to 1,000 characters. At most 32 scripts are advertised. Parameter schemas must have `type: object` and `additionalProperties: false`; external/recursive `$ref` schemas are not supported. Inputs are validated before launch and limited to 16 KiB of JSON.

Scripts receive a JSON object on **standard input**, not command-line arguments. Print results to standard output and errors to standard error; use a nonzero exit code to report failure. A minimal example:

```python
import json
import sys

arguments = json.load(sys.stdin)
print(json.dumps({"uppercase": arguments["text"].upper()}))
```

In the app, open **Saved scripts** to view the registry, then enable **Allow saved scripts** in your chat. Ask, for example: “Use the add_numbers saved script to sum 2 and 3.” Your Ollama model must support tool calling. A profile can enable script access by default; existing chats keep their copied preferences until explicitly updated.

## Execution environment

The runner is a separate Linux Docker container on the computer running this app, not the remote Ollama machine. This folder is mounted read-only. A script runs as a non-root user using an isolated Python interpreter (`-I -u -X utf8`) with JSON stdin, a clean environment and a fresh temporary working directory, deleted afterward. The default dependencies are Python's standard library; sibling-file imports are not automatically added to Python's search path in isolated mode. For additional packages, add pinned dependencies to `script_runner/requirements.txt` and rebuild the runner. No packages are installed on demand by the model.

The container has no external network, chat-database mount, host home-directory mount, Docker socket, or board/device mappings. The system filesystem and saved scripts are read-only. Writable locations are the 64 MiB temporary filesystem and the small private socket volume used to communicate with the backend; scripts should write only in their temporary working directory. There is no published port. Scripts can read their own container filesystem, not arbitrary host folders. These restrictions do **not** make untrusted Python safe: register code you have reviewed and trust.

Defaults are one script at a time, 30 seconds per run, 32 KiB combined stdout/stderr capture, 4 calls per user message, 256 MiB container memory, 1 CPU and 64 container processes. Excess output stops the script and marks the result truncated. Timeouts, Stop/disconnect and task cancellation terminate the script process group on Linux; deliberately adversarial code can evade ordinary process-group cleanup and is not supported. Resource limits apply to the whole runner. Busy requests return an error instead of queuing indefinitely.

Script results (name, arguments, captured output, errors, exit code, duration and status) appear in chat and are saved with its history. Reopening a chat does not rerun scripts. The model receives actual tool results for its follow-up answer. Incomplete tool exchanges are excluded from future model context. There is no API for the model to create/edit scripts, run a shell, or execute code from its answer. No Arduino validation or upload script is supplied.

## Updating and configuring

Changes to saved `.py` files or `tools.json` are read on the next call; use **Refresh scripts** to update the displayed catalog. Rebuild for runner dependencies or implementation changes:

```powershell
docker compose up --build -d
```

Root `.env` settings:

- `SCRIPT_TOOLS_ENABLED=true`: enable the server feature (the chat must also opt in). Set `false` to disable all execution.
- `SCRIPT_TIMEOUT_SECONDS=30`: run timeout, clamped to 1–120 seconds.
- `SCRIPT_OUTPUT_BYTES=32768`: combined capture limit, clamped to 1,024–131,072 bytes.
- `SCRIPT_MAX_CALLS=4`: per-message call limit, from 1 to 8.

Saved scripts are supported through Docker Compose. Standalone backend development defaults to execution disabled; on Linux a separately started runner can use `SCRIPTS_DIRECTORY` and the backend's `SCRIPT_RUNNER_SOCKET` setting. Do not run unfamiliar scripts directly on the host to bypass container restrictions.
