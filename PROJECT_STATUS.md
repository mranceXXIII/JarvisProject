# JARVIS Project Status

**Current phase:** Phase 2 complete — API manager and AI brain.
**Date:** 2026-10-31

## Completed features

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

## Files created or changed (Phase 2)

```text
requirements.txt (+requests==2.34.2)
config/routing.yaml
core/config_loader.py (+RoutingConfig), core/ai_router.py, core/assistant.py
providers/errors.py, providers/http_client.py, providers/base_adapter.py (rewritten),
providers/openai_compatible.py, providers/ollama_adapter.py,
providers/gemini_adapter.py, providers/anthropic_adapter.py,
providers/provider_manager.py
interface/api_gateway_panel.py, interface/dashboard.py (tabs), main.py (wiring)
tests/fakes.py, tests/test_openai_compatible_adapter.py,
tests/test_other_adapters.py, tests/test_router_and_manager.py,
tests/test_assistant.py
```

## Tests passed

- **87 passed, 0 failed** (`python -m pytest`, Python 3.14, Windows).
- All provider/HTTP interaction is tested with fake sessions — **no real
  network calls, no real API keys, no real emails** in tests.
- Smoke test: `python main.py --headless` starts, loads providers/gateways
  and routing mode, idles cleanly.

## Known limitations (stated honestly)

- **No streaming** and no structured-output enforcement yet; adapters
  declare those capabilities conservatively.
- **Provider endpoints are pinned to current public URLs** in
  `PROVIDER_TYPE_DEFAULTS` and should be re-verified against each provider's
  official documentation before production use; users can override
  `base_url`/`endpoint_path` per provider.
- **Tool calls are surfaced, not executed.** Execution, permission checks,
  and approval dialogs arrive in Phase 4.
- **Chat UI is not wired yet.** The assistant API exists and is tested; the
  dashboard chat panel connects once memory (Phase 3) is available to
  persist conversations.
- **No API-key input UI yet.** Store keys in Windows Credential Manager
  manually (e.g. `keyring set JARVIS jarvis/<ref>`) until the settings UI
  adds credential entry.
- Memory/persistence still pending (Phase 3).

## Next tasks (Phase 3 — Memory)

1. SQLite storage of conversations, task outcomes, and metadata.
2. Full-text search; optional semantic retrieval.
3. Backup/export/deletion controls; persistence verified after restart.
4. Wire chat panel through the assistant with conversation persistence.
