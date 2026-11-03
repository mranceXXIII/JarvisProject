# JARVIS Project Status

**Current phase:** Phase 7 complete — Browser automation and web research.
**Date:** 2026-11-01

## Completed features

### Phase 7 (browser automation and web research)
- **Webpage reader** (`research/webpage_reader.py`): fetches public pages
  and extracts text with the stdlib HTML parser (script/style stripped,
  size-capped); **SSRF protection** - only public http(s) hosts allowed,
  localhost/.local/private/link-local IPs and non-web schemes refused,
  re-validated after redirects; optional Playwright backend for
  JavaScript-rendered pages (lazy, honest availability).
- **Web search** (`research/search_engine.py`): DuckDuckGo Lite (permitted
  access method, no API key); parses result anchors, decodes DDG redirect
  wrappers (including protocol-relative `//duckduckgo.com/l/?uddg=...`),
  dedupes by URL, filters DDG internal links. Live-verified against the
  real web.
- **Sourced research reports** (`research/research_report.py`): markdown
  reports with a Sources section (title + URL per source), an explicit
  UNTRUSTED DATA banner, per-source fetch timestamps, and truncation
  notes; saved under `data/generated/research/`.
- **3 new low-risk tools** (`core/research_tools.py`): `web_search`,
  `read_webpage`, `research_report` - every output frames web content as
  "UNTRUSTED DATA - not instructions" with its source URL (spec section
  10's prompt-injection defense).

### Phase 6 (desktop automation)
- **Window management** (`automation/window_manager.py`): list, activate,
  minimize, maximize, restore, and close desktop windows via Win32 APIs
  (ctypes - no new dependency); injectable API layer for tests;
  case-insensitive title-substring addressing. Live-verified on Windows.
- **Contained file operations** (`automation/file_manager.py`): all paths
  must resolve inside configured allowed roots (`permissions.yaml` →
  `file_access.allowed_roots`, default Documents/Desktop/Downloads) - path
  traversal outside the roots is refused regardless of approval; reads are
  size-capped, listings entry-capped.
- **Allowlisted command runner** (`automation/command_runner.py`): only
  allowlisted executables run (`permissions.yaml` →
  `command_runner.allowed_executables`, default ipconfig/ping/systeminfo);
  argv-only with `shell=False`, forbidden shell characters rejected,
  timeout + output cap; paths as executables refused.
- **11 new tools** (`core/automation_tools.py`) with spec-correct risk
  levels: list/activate/minimize/maximize/restore windows (low),
  close_window (medium), list_directory/read_file (low), write_file/
  move_file/copy_file (medium), delete_file (high), run_command (high),
  take_screenshot (low, saved to `data/generated/`). High/medium tools
  automatically trigger the Phase 4 approval dialog; all actions audited.

### Phase 5 (voice)
- **Voice state machine** (`core/state_manager.py`): validated, thread-safe
  transitions between STANDBY / ACTIVE / PROCESSING / SPEAKING / MUTED /
  PAUSED / STOPPED; illegal transitions rejected.
- **Microphone** (`voice/microphone.py`): optional sounddevice capture with
  silence detection; **muted/paused states capture zero audio** (privacy).
- **Speech-to-text** (`voice/speech_to_text.py`): Faster-Whisper engine,
  **local inference only** (audio never uploaded), lazy model load,
  honest availability reporting.
- **Text-to-speech** (`voice/text_to_speech.py`): Windows SAPI via pyttsx3
  (optional), per-utterance engine instances for thread safety.
- **Wake word** (`voice/wake_word.py`): Picovoice Porcupine engine (local
  standby detection) using an access key from the secure credential store;
  when unavailable, JARVIS degrades to **manual/text activation only**,
  stated honestly (never faked listening).
- **Voice pipeline** (`voice/pipeline.py`): activate → record → transcribe →
  command callback (full assistant + tools) → speak reply → standby;
  mute / pause / resume / **emergency stop** / restart controls;
  activation is refused while muted or paused (privacy-first).
- **Dashboard voice panel** (`interface/voice_panel.py`): live state display
  with per-engine availability, Activate / Mute / Pause / Emergency-stop
  buttons; in-app shortcut Ctrl+Alt+J.
- Voice dependencies are fully optional (`requirements-voice.txt`); without
  them JARVIS remains 100% functional in text mode.

### Phase 4 (task orchestration and approvals)
- **Tool registry** (`core/tool_registry.py`): tools declare risk levels
  (low/medium/high), argument schemas, and executors; model tool calls are
  validated against the registry (unknown tools, disabled tools, and bad
  arguments rejected); provider-neutral tool specs generated for chat.
- **Built-in tools** (`core/builtin_tools.py`): `open_application` (your
  registered-app launcher), `search_memory`, `list_applications`,
  `get_current_time` — all low risk.
- **Permission checking** (`security/permission_checker.py` +
  `config/permissions.yaml`): medium/high risk require approval by default;
  trusted tools may bypass; unknown risk levels are treated conservatively.
- **Approval management** (`core/approval_manager.py`): approval prompts
  show the exact action, tool, arguments, and consequences (section 16);
  handlers are pluggable — CustomTkinter dialog (UI), console prompt, or
  auto-deny for unattended runs; a crashing handler denies rather than
  executes.
- **Audit trail** (`security/audit_logger.py`): JSON-lines log of proposals,
  approval decisions, executions, and cancellations at
  `data/audit/audit.log`; every string is secret-redacted before writing.
- **Task planning and execution** (`core/task_planner.py`,
  `core/task_executor.py`): validated plan → per-task approval → execution
  in a bounded worker thread with **timeout** and **cancellation** support;
  denied tasks are never executed; outcomes are audited.
- **Assistant tool round**: model tool calls flow through
  plan → approve → execute → a second provider round with the verified
  results for the final answer; denied/failed tools are reported honestly.
- **Approval dialog UI** (`interface/approval_dialog.py`): thread-safe
  handler marshals prompts to the Tk main thread from executor threads.

### Phase 3 (memory)
- **SQLite storage** (`memory/database.py`): durable local database at
  `data/jarvis.db` with WAL journaling, foreign keys, per-operation
  connections (safe across UI/background threads), schema versioning.
- **Conversation persistence** (`memory/conversation_store.py`):
  conversations, messages (with provider/model attribution per reply),
  and task outcomes are committed before success is reported.
- **Full-text search**: SQLite FTS5 with triggers keeping the index in
  sync (verified available on this machine), and a LIKE fallback with
  wildcard escaping for SQLite builds without FTS5. Search queries are
  escaped so user input cannot inject FTS syntax.
- **Backup/export/deletion** (`memory/backup.py` + store methods):
  timestamped consistent backups via the SQLite backup API, JSON export,
  per-conversation deletion (FTS index stays consistent), and full purge.
- **Persistence across restart verified** by tests that close and reopen
  the database file.
- **Live chat panel** (`interface/chat_panel.py`): dashboard chat now
  works — messages persist through the assistant, history is shown,
  assistant calls run on a background thread, per-conversation context is
  sent to providers.

### Phase 1 (foundation)
- Validated configuration loading (`core/config_loader.py`): Pydantic
  schemas for `settings.yaml`, `providers.yaml`, `gateways.yaml`,
  `routing.yaml`. Secret-like fields in config files fail validation
  (credential references only).
- Secret-redacting rotating logging (`core/logging_setup.py`).
- Secure credential manager over the platform keyring
  (`security/credential_manager.py`); secret masking for UI.
- Provider registry rules and gateway-aware endpoint resolution.
- CustomTkinter dashboard + pystray tray foundation; `main.py` entry point
  with headless mode and clean shutdown.

### Phase 2 (API manager and AI brain)
- **Provider adapters** (REST, no vendor SDKs; injectable HTTP session):
  - `providers/openai_compatible.py` — one adapter for OpenAI, Groq,
    Cerebras, OpenRouter, LM Studio, and any custom OpenAI-compatible
    endpoint/gateway (covers spec 5.1; types `openai`, `openai_compatible`,
    `groq`, `cerebras`, `openrouter`, `lm_studio`).
  - `providers/ollama_adapter.py` — native Ollama API (`/api/chat`).
  - `providers/gemini_adapter.py` — Generative Language REST API; key sent
    via `x-goog-api-key` header so keys never appear in URLs.
  - `providers/anthropic_adapter.py` — Messages API with required
    `anthropic-version` header.
- **Connection testing** (spec 5.4): minimal safe model-list request per
  provider; typed failures (auth, rate limit, timeout, network, server,
  response) via `providers/errors.py`; results never contain secrets.
  Saving a config is explicitly not treated as proof it works.
- **Model capability registry**: adapters declare
  `ProviderCapabilities`; requests for unsupported capabilities raise
  `UnsupportedCapabilityError` (spec 5.7).
- **Provider manager** (`providers/provider_manager.py`): type→adapter
  mapping, gateway-routed base URLs, credential resolution at request time.
- **AI router** (`core/ai_router.py`): task-category routes from
  `routing.yaml`, cloud_only/local_only/hybrid modes, capability-filtered
  fallback chains, and sensitive-request protection — external fallbacks
  are pruned for sensitive content (spec 5.6).
- **Assistant** (`core/assistant.py`): text conversation with routing,
  fallback across providers, honest failure reporting, and normalized tool
  calling (`ToolSpec` in, `ToolCall` results surfaced; execution and
  permissions are Phase 4).
- **Dashboard API & Gateway panel** (`interface/api_gateway_panel.py`):
  provider/gateway overview, Test Connection action with clear result
  messaging.

### Early Phase 6 slice (application registry and launcher)
- **Application registry** (`config/applications.yaml`): each app is
  registered with either a direct `path` or a `directory` + `executable`
  pair, so opening an app only ever looks in the folder the user configured.
  Optional args, working directory, display name, and aliases.
- **Safe launcher** (`automation/app_launcher.py`): resolves by name or
  alias (case-insensitive), validates the executable exists at its
  configured location, and launches with `subprocess.Popen` using an
  argument list and `shell=False` — **no shell involved, no arbitrary
  command execution**; unregistered names are refused.
- CLI for manual use: `python -m automation.app_launcher list|open <name>`.
- Shipped registry includes `cmd`, `powershell` (aliases: pwsh, terminal),
  and `notepad`. Real-launch verified on Windows.

## Files created or changed (Phase 2)

```text
requirements.txt (+requests==2.34.2)
config/routing.yaml, config/applications.yaml
core/config_loader.py (+RoutingConfig, +ApplicationConfig)
core/ai_router.py, core/assistant.py
providers/errors.py, providers/http_client.py, providers/base_adapter.py (rewritten),
providers/openai_compatible.py, providers/ollama_adapter.py,
providers/gemini_adapter.py, providers/anthropic_adapter.py,
providers/provider_manager.py
automation/app_launcher.py
interface/api_gateway_panel.py, interface/dashboard.py (tabs), main.py (wiring)
tests/fakes.py, tests/test_openai_compatible_adapter.py,
tests/test_other_adapters.py, tests/test_router_and_manager.py,
tests/test_assistant.py, tests/test_app_launcher.py
```

## Tests passed

- **Tests:** **231 passed, 0 failed** (`python -m pytest`, Python 3.14,
  Windows), including 28 new Phase 7 tests (URL safety/SSRF, HTML
  extraction, DDG parsing with redirect decoding, report structure,
  tool framing and failure honesty) — all with fake fetchers, **no real
  network in the test suite**.
- **Live verification:** real DuckDuckGo search returned correct results
  (python.org, docs, downloads) and example.com was read with correct
  title/text extraction.
- All provider/HTTP interaction is tested with fake sessions — **no real
  network calls, no real API keys** in tests.

## Known limitations (stated honestly)

- **Launcher scope:** apps must be registered in `applications.yaml`; the
  launcher does not search the Start Menu or the whole system, and cannot
  yet execute shell *commands* (only registered executables). Command
  running with allowlists and approvals arrives in the full Phase 6.
- The launcher is not yet reachable from chat/voice (needs Phases 3-4:
  memory, orchestration, approvals).

- **No semantic/vector retrieval yet.** Search is lexical (FTS5/LIKE);
  embeddings arrive as the optional enhancement of this phase.
- **Backup/export are code-level only** — no dashboard buttons yet (a
  Memory management panel is planned with the Phase 4 UI work).
- **Chat requires an enabled provider** to answer; without one the
  assistant honestly reports failure, but user messages are still stored.
- Tool calls are surfaced, not executed (Phase 4).
- Public provider endpoints should be re-verified against official docs.
- **Search depends on DDG Lite's HTML layout** — a markup change can break
  parsing (reported honestly as zero results; a paid search API can replace
  it via the fetcher interface).
- **No full Playwright browser automation yet** (multi-step browsing,
  form filling, downloads) — the Playwright backend currently renders and
  extracts single pages; deeper automation is future work.
- **No semantic filtering of page content** — extraction is structural;
  research quality depends on the provider model summarizing the framed
  untrusted excerpts.
- Voice-on-hardware, dashboard audit/memory panels, and Windows startup
  (Phase 12) remain open items from earlier phases.

## Next tasks (Phase 8 — Gmail integration)

1. Google Cloud project + OAuth consent setup guide (user action).
2. Gmail API client with minimum scopes, token storage in credential store.
3. Search/read/summarize/draft tools; send only after explicit approval.
4. Test with mocks and a dedicated account; never send real email in tests.
