# Chappie — milestone 1

A React + TypeScript + Vite client with a FastAPI backend. Ollama runs on your model computer; Tailscale runs on the hosts. Docker Compose runs the interface on your client computer. SQLite stores conversations in a named Docker volume, managed through SQLAlchemy and Alembic.

## Retro interface

The frontend uses an off-beige pixel-inspired light theme and a clean gunmetal dark theme, both with navy-blue interaction accents. Dark mode adds subtle brushed-metal panels, a muted gold chain and dollar-sign pendant in the sidebar, and small orange robotic-arm and antenna details. The original Chappie icon is used throughout. Switch themes at the bottom of the sidebar; the choice is saved in this browser. On small screens, the menu button opens the sidebar. Chat search filters saved conversation titles, grouped into Today and Earlier.

Replies preserve their original text. Fenced code blocks and recognizable plain Python/JavaScript replies appear in code panels with a Copy button. Common fenced languages have syntax highlighting after streaming finishes; unsupported languages remain plain code. Highlighting is also skipped for code blocks over 50,000 characters to keep the interface responsive. Display formatting never executes, repairs, or rewrites model-generated code. Connection details expand from the status strip, and response timing remains available below the last answer. Green/amber/red communicate health independently of the navy selection color.

The Pixelify Sans font is bundled locally with its SIL Open Font License in `frontend/src/assets/PixelifySans-OFL.txt`; no external font service is needed. Conversation text and code use readable system monospace fonts. Saved-script tools are optional; automatic skill execution remains unimplemented.

## Assistant profiles

Use **Assistant profiles** in the sidebar to create or edit a specialist. An editable **Arduino Developer** starter is included. A profile contains a name, description, instructions, default project context, reference notes, preferred installed model, and a reasoning preference. Leaving the preferred model blank keeps the currently selected model. Profiles configure model requests; they do not train or download models.

Select an **Assistant** above the conversation. Its model/reasoning preferences are applied, and **Project context** lets you set board, components, pin assignments, library versions, or other notes for that chat. You can also use project context with General assistant. A preferred model that is unavailable prompts you to choose an installed model instead of silently substituting one. Reasoning preferences use the existing on/off controls for supported Qwen models; Thinking variants retain their normal handling.

Each chat stores a copy of its profile's instructions, references, and name. It also remembers the last-used model and effective reasoning setting after a message is sent. Editing a profile applies to new chats; an existing chat offers **Update chat from profile** to explicitly refresh its copy while preserving its project context. Selecting a different assistant replaces its copied configuration and initializes that assistant's default project context for subsequent messages, keeping all chat messages. Deleting a profile removes it from the selector but retains saved copies in existing chats. New chat keeps the current assistant where that profile still exists, using its latest defaults.

Reference notes can be pasted or imported from `.md` / `.txt` files, including a SKILL.md file. Import appends plain text to the notes; it never executes file contents or enables tools. Limits per profile are 12,000 characters for instructions, 12,000 for default project context, and 24,000 for reference notes. All references and the chat's project context are sent with each request, not searched or retrieved selectively. Keep them relevant to avoid exhausting the model's context window. Assistant-specific instructions take precedence over the general concise-response style; reference notes are labeled as source material.

The Arduino profile asks about missing board/wiring/library details and helps draft sketches. **No Arduino CLI, compilation, hardware access, or board upload tool is implemented.** It can optionally use registered saved Python scripts like any other profile. Profiles and their chat copies live in the same persistent SQLite database as chats. The Alembic `0002` migration preserves existing conversations and messages and adds the starter only on first upgrade.

## Saved Python scripts

Place trusted scripts in the project-local `scripts/` folder and register them in `scripts/tools.json`. Open **Saved scripts** in the sidebar to inspect the catalog, then enable **Allow saved scripts** in a chat. Profiles can enable access by default; each chat remembers its choice after sending a message. A tool-capable Ollama model is required. Try: “Use the add_numbers saved script to sum 2 and 3.” Two examples, `add_numbers` and `text_stats`, are included.

The model receives named function schemas, not a shell. Registered scripts take validated JSON on stdin and run in a separate non-root, network-disabled container. The saved folder is read-only; the runner has no chat database, home-directory, hardware, or Docker-socket mount. It communicates with the backend over a private Unix socket. Default limits are 30 seconds per script, 32 KiB combined output, 4 calls per message, and one script at a time. Stop/disconnect requests cancel execution. Script names, arguments, actual output/errors, exit status and duration are saved and displayed in chat; reopening history does not execute anything.

Only register scripts you trust: folder restrictions and container limits do not make arbitrary Python safe. There is no API for the model to write scripts or execute code from its answers. See [scripts/README.md](scripts/README.md) for the registry format, execution environment, limits and dependencies. The `0003` migration preserves existing messages, adds persistent tool-call fields, and keeps script access off in existing chats/profiles until explicitly enabled.

## Start with Docker (recommended)

Prerequisites: Docker Desktop with the Linux engine running, Docker Compose, and Tailscale signed in on both computers. Ollama must already be installed on the model computer with at least one downloaded model.

1. On the **client computer**, check your model host:

   ```powershell
   tailscale status
   tailscale ping <model-host>
   curl.exe http://<model-tailscale-ip>:11434/api/tags
   ```

2. On the **model computer**, make Ollama listen on an address reachable over Tailscale. Ollama defaults to loopback. Set `OLLAMA_HOST` in the environment of the Ollama service/process and restart it. You can bind it to the model computer's Tailscale IPv4 address, such as `100.101.102.103:11434`. If you bind `0.0.0.0:11434`, restrict inbound access with the host firewall and tailnet access rules. Ollama's local API has no authentication; do not expose it publicly. Pull models on that computer with `ollama pull <model-name>`.

3. In this project directory:

   ```powershell
   Copy-Item .env.example .env
   ```

   Edit `.env` to set `OLLAMA_BASE_URL=http://<model-tailscale-ip>:11434`. Use the origin only, without `/api`. A MagicDNS name also works if Docker can resolve it; use the Tailscale IP if host DNS works but container DNS does not.

4. Build and start:

   ```powershell
   docker compose up --build -d
   docker compose ps
   ```

5. Open [http://localhost:8080](http://localhost:8080). Refresh connection and models, select a model, and send a message. Enter sends; Shift+Enter adds a line. Use **New chat** and the sidebar to switch conversations. Model changes affect subsequent turns in the current chat.

The browser talks only to the interface's same-origin `/api`. The backend calls Ollama, so Ollama browser CORS configuration is unnecessary. No Ollama or Tailscale container is included.

If Ollama runs on the client host instead, use `OLLAMA_BASE_URL=http://host.docker.internal:11434`; it must accept connections from Docker. `localhost` inside the backend refers to the backend container. Linux Compose includes a host-gateway mapping; host networking/firewall behavior still depends on your OS.

## Connection diagnostics

The refresh button runs separate checks:

| Check | Meaning |
| --- | --- |
| Network | DNS resolution and TCP connection to the configured Ollama host/port. A successful result does not prove that the service is Ollama or that traffic used Tailscale. |
| Ollama | A valid `/api/tags` response. Empty model lists are valid; install a model on the remote host before chatting. This does not guarantee that a model fits in memory or can generate. |
| Tailscale | Always **unknown** here. A container cannot infer host login, peer connectivity, or routing from an HTTP request. Verify with `tailscale status` and `tailscale ping <model-host>` on the client host. |

The host can have a working Tailscale connection while Docker cannot reach the peer due to DNS, routing, VPN integration, or firewall settings. A reachable TCP port with an unavailable Ollama result means the API check failed independently. The backend `/api/health` checks the interface process, so you can still open saved chats while Ollama is offline.

## Storage and streaming

The `chat-data` volume holds `/app/data/chats.db`. Migrations run before the backend starts. `docker compose down` preserves the volume. **`docker compose down -v` deletes the stored chats.** For a consistent backup, stop the backend before copying the volume's database files, including any WAL files.

Responses stream as newline-delimited JSON (`start`, `status`, `delta`, `done`, `error`). User messages are committed before generation. Assistant text is delivered immediately and checkpointed at most twice per second during output; completion, errors, and disconnect cleanup save the latest text. Errors, Stop, and disconnects preserve partial output with an error/interrupted status. An abrupt process termination may lose text since the last checkpoint (normally up to 0.5 seconds of active output); startup marks remaining streaming messages interrupted. Incomplete assistant replies remain visible but are excluded from later model context; user messages remain in context. Thinking traces are not displayed or stored; a status message indicates that the model is thinking.

When scripts are used, the stream additionally emits `tool_calls`, `tool_start`, `tool_result`, and `assistant_start` events. Each complete assistant/tool exchange is persisted. Interrupted tool exchanges remain visible but are excluded from later model context. Model load/prompt/generation timings are summed across model rounds; total wall time also includes script execution.

## Slow first responses and Qwen3

The UI inspects the selected model through Ollama `/api/show`. For Qwen3 and Qwen3.5 models that report thinking support, **Qwen reasoning (slower)** defaults to off and sends `think: false`. Enable the checkbox when you want reasoning; the interface sends `think: true` and shows “Model is thinking…” when thinking chunks arrive. This setting is local to the open browser page and resets to off on reload. It does not change model weights or other clients. Use a recent Ollama version supporting the model's thinking controls.

Some tags point to dedicated Thinking variants rather than hybrid/instruction variants. For a Qwen3 model reporting `general.finetune=Thinking`, the UI warns that disabling reasoning may be ineffective and hides the misleading on/off toggle. It omits `think` for that variant, allowing Ollama to handle normal thinking output separately instead of potentially exposing it as answer text. Models explicitly reporting no thinking capability also have no toggle. Other model families retain their defaults. Capability checks temporarily disable Send while loading; if inspection fails, the UI warns that the available toggle may not apply.

If your `qwen3:4b` identifies as Thinking and continues planning aloud, a style prompt cannot reliably turn it into a direct-answer model. An existing Qwen3.5 model with reasoning off may be an alternative. A separately downloaded `qwen3:4b-instruct` is another option, but the interface never installs or replaces models automatically. Model aliases can change: inspect the actual downloaded variant rather than assuming capabilities from a tag alone.

For API clients, `think` is an optional boolean on the message request; omitting it preserves Ollama's model default. Models with named reasoning levels instead of on/off controls need separate support; the Qwen3 checkbox is intentionally limited to the base Qwen3 model family.

After each completed response, expand **Last response timing**. The first model activity, first answer text, and total durations are measured by the backend from entry to its message handler. They include preflight, database setup, network waits, model loading, queuing, prompt processing and generation; they are not pure network latency and exclude browser-to-backend time. Model loading, prompt processing, generation and tokens/second come from Ollama's final response when available. These measurements are shown for the latest response in the current page only, not stored in chat history. Thinking tokens can contribute to generation time/counts even before visible answer text.

For a fair comparison, select exactly the same model tag, reasoning setting and context on the desktop and laptop. Start a **New chat** and send “Hello” twice, waiting for the first request to finish. A slow first request with high model-loading time suggests a cold model; a slow first-answer time after early model activity can indicate reasoning. This is a diagnostic clue, not proof of the cause. The app requests a 10-minute model keep-alive by default to reduce repeated cold starts; this retains host memory longer but does not warm a model before the first request or prevent eviction when other models need memory.

If the delay remains, run `tailscale ping <model-host>` on the laptop. It reports whether the peer connection is direct or relayed; `tailscale netcheck` can help diagnose a relay connection. On the desktop, `ollama ps` reports whether the model uses GPU, CPU, or a mixture. Avoid changing context size blindly: shorter contexts can reduce resource use but also reduce conversation capacity. Compare the same settings before tuning them.

References: [Ollama thinking controls](https://docs.ollama.com/capabilities/thinking), [Ollama keep-alive and GPU usage](https://docs.ollama.com/faq), [Tailscale performance troubleshooting](https://tailscale.com/docs/reference/troubleshooting/poor-performance-tailnet).

This milestone supports one backend process/worker and one active generation per chat. Keep `--workers 1`; the generation guard is in memory. Completed chat history and complete tool exchanges are sent to Ollama; incomplete tool exchanges are skipped. Context truncation, pagination, authentication, multiuser isolation, and general-purpose tools are future work. The frontend port binds to the client's loopback interface by default for this personal app.

## Concise answers

By default, every model request starts with an application system instruction to answer directly, skip filler, and return only a complete code solution for programming requests unless explanation is requested. Explicit requests for more detail or another format take precedence within that style instruction. It applies to new turns in both new and existing chats. It is sent once per request and is not stored as a chat message.

This is prompt guidance, not fine-tuning or a guaranteed word limit. There is no new output-token cap, so complete programs can finish. Start a new chat when comparing response styles so previous verbose responses do not influence the result. Set `CHAT_RESPONSE_STYLE=model_default` in `.env` to omit the style instruction, or keep `concise` (the default). Apply configuration changes with `docker compose up --build -d`. This changes this interface's requests, not the model installation or other clients. The default instruction lives in `backend/app/prompts.py`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama origin configured on the server, never user-supplied per request. |
| `APP_PORT` | `8080` | Compose frontend port on `127.0.0.1`. |
| `OLLAMA_READ_TIMEOUT` | `180` | Maximum idle wait between Ollama response chunks, in seconds. |
| `OLLAMA_KEEP_ALIVE` | `10m` | How long Ollama should retain the model in host memory after a request; accepts Ollama durations such as `5m` or `10m`. |
| `CHAT_RESPONSE_STYLE` | `concise` | `concise` injects direct-answer/code-only guidance; `model_default` omits it. |
| `SCRIPT_TOOLS_ENABLED` | `true` in Compose; `false` standalone | Enable saved-script tools on the server; chats must also opt in. |
| `SCRIPT_TIMEOUT_SECONDS` | `30` | Runner timeout, clamped to 1–120 seconds. |
| `SCRIPT_OUTPUT_BYTES` | `32768` | Combined raw stdout/stderr byte limit. |
| `SCRIPT_MAX_CALLS` | `4` | Maximum script calls per user message (1–8). |
| `DATABASE_URL` | `sqlite:///./data/chats.db` | Local backend database; Compose fixes this to its persistent volume. SQLite is the supported database. |
| `DIAGNOSTIC_TIMEOUT` | `5` | Local backend probe timeout in seconds; set in Compose environment to override there. |

Nginx's upstream idle timeout is 240 seconds. If increasing the Ollama timeout beyond that, also adjust `frontend/nginx.conf`.

## Local development and tests

Python 3.12 and Node 24 are the tested runtimes. The frontend uses pnpm 11.25.0 with a committed lockfile (install with `npm install --global pnpm@11.25.0`).

From the project root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend/requirements-dev.txt
.\.venv\Scripts\python -m pytest backend/tests -q
```

Start the backend in one terminal (the root Compose `.env` is not automatically read after changing directory; set the URL below):

```powershell
cd backend
$env:OLLAMA_BASE_URL = 'http://<model-tailscale-ip>:11434'
..\.venv\Scripts\python -m alembic upgrade head
..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal:

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open the URL Vite prints. Its `/api` proxy targets `127.0.0.1:8000`. To verify a production frontend build, run `pnpm build`. `pnpm preview` serves static assets only; use Compose to test production API proxying.

Backend tests use temporary real SQLite databases with migrations and mocked Ollama responses. They cover streaming, history/context, model switching, failed/truncated output, preflight failures, validation, generation conflicts, restart persistence, interrupted-message recovery, and migration rollback/reapply. A live HTTP test additionally starts a fake model server and backend to verify incremental delivery and disconnect cleanup. No remote model is required for tests. For a real-host smoke test, send a prompt in the UI, confirm text arrives progressively, refresh the browser, and reopen it from the sidebar. Stop Ollama and refresh diagnostics to check the failure display.

## Future integration scaffolds

`skills/` and `backend/app/skills/` are reserved for future automatic SKILL.md discovery. `backend/app/tools/` implements only the saved-script bridge and complete-tool-history handling. Explicitly imported reference files are plain text only; no skill runtime, calendar access, or external-service credentials are implemented.

## API and references

FastAPI's interactive API reference is available at `http://127.0.0.1:8000/docs` during local backend development. Compose exposes only the frontend.

- `GET /api/health`, `GET /api/diagnostics`, `GET /api/models`, `GET /api/model-info?model=<name>`
- `GET /api/scripts` returns feature availability and registered script schemas; execution is offered only through enabled chat tool calls, not a public arbitrary-run endpoint.
- `GET /api/chats`, `POST /api/chats`, `GET /api/chats/{id}`
- `POST /api/chats/{id}/messages` with `{ "model": "installed-name", "content": "Hello" }`
- `GET /api/assistants`, `POST /api/assistants`, `PUT /api/assistants/{id}`, `DELETE /api/assistants/{id}`
- `POST /api/chats` optionally accepts `{ "assistant_id": "profile-id", "project_context": "chat-specific notes" }`
- `PATCH /api/chats/{id}/assistant` selects/copies a profile; `PATCH /api/chats/{id}/context` updates only the chat's project context. Both reject changes during generation.

Profile fields: `name`, `description`, `instructions`, `project_context`, `reference_notes`, `preferred_model`, `reasoning` (`off`, `on`, or `model_default`), `script_tools_enabled` (default false). For a profile chat, omitting `think` from the message request uses its saved reasoning preference; supplying `think: null` explicitly requests the model default. An explicit boolean overrides the preference. Without a profile, omission retains the previous API behavior (model default). Message requests accept `use_scripts`: an explicit boolean overrides and saves the chat's script preference; omission uses its saved value. Server configuration must also permit scripts.

Upstream references: [Ollama chat streaming](https://docs.ollama.com/api/chat), [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling), [installed-model list](https://docs.ollama.com/api/tags), [Tailscale and Docker](https://tailscale.com/docs/solutions/host-private-server-docker).
