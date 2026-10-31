# JARVIS --- Personal AI Desktop Assistant

A customizable, hybrid AI assistant for **Windows 10/11**, built with
Python. JARVIS is intended to combine voice and text interaction, a
desktop dashboard, a background system-tray process, configurable AI
providers and gateways, persistent memory, and approval-controlled
automation.

> **Project status:** This repository is a development specification and
> project scaffold plan. The features described below are goals, not
> claims that a working implementation already exists. Build and verify
> the application incrementally.

## Table of contents

-   [Project goals](#project-goals)
-   [Key features](#key-features)
-   [Architecture](#architecture)
-   [Requirements](#requirements)
-   [Getting started](#getting-started)
-   [Configuration](#configuration)
-   [Security and approvals](#security-and-approvals)
-   [Development roadmap](#development-roadmap)
-   [Project structure](#project-structure)
-   [Testing](#testing)
-   [Documentation](#documentation)
-   [Contributing](#contributing)

## Project goals

JARVIS should be a practical desktop assistant that can understand
requests, plan work, use approved tools, and report verified outcomes.
It should be modular and provider-independent so that new capabilities
can be added without rewriting the core application.

Design priorities:

1.  **User control:** ask before important or sensitive actions.
2.  **Provider independence:** do not lock the application to one AI
    vendor.
3.  **Local-first options:** support local and open-source components
    where practical.
4.  **Extensibility:** add capabilities through well-defined plugins and
    integrations.
5.  **Privacy and security:** protect credentials and avoid exposing
    sensitive content in logs.
6.  **Reliability:** verify tool results and handle errors rather than
    claiming unverified success.

## Key features

The planned application includes:

-   **Voice and text:** configurable wake phrase (for example, "Hey
    JARVIS"), manual activation, speech recognition, and text-to-speech.
-   **Windows presence:** optional startup with Windows, lightweight
    standby, system-tray controls, and a desktop dashboard.
-   **Universal API & Gateway Manager:** add, edit, test, activate,
    deactivate, and remove AI providers and gateways from the dashboard.
-   **Flexible AI routing:** choose providers and models by task,
    configure fallback chains, and optionally use local models.
-   **Persistent memory:** local records of conversations, preferences,
    task outcomes, generated-file references, and project history.
-   **Desktop automation:** interact with supported Windows applications
    through controlled automation modules.
-   **Web research:** browser automation and research workflows, with
    source-aware summaries.
-   **Integrations:** planned connectors such as Gmail and selected
    messaging or productivity services, subject to their APIs and
    permissions.
-   **Plugin system:** propose, develop, test in staging, review, and
    explicitly approve new skills before installation.

## Architecture

The application should be separated into modules with clear interfaces:

  -----------------------------------------------------------------------
  Layer                               Responsibility
  ----------------------------------- -----------------------------------
  Interface                           Dashboard, text chat, tray menu,
                                      settings, and approval prompts

  Core assistant                      Conversation handling, planning,
                                      task orchestration, and result
                                      reporting

  Provider manager                    Provider/model definitions, API
                                      requests, health checks, and
                                      routing

  Gateway manager                     Configurable API base URLs, gateway
                                      endpoints, headers, and
                                      authentication

  Voice                               Wake-word detection,
                                      speech-to-text, and text-to-speech

  Memory                              SQLite persistence and optional
                                      semantic retrieval

  Automation                          Controlled desktop and browser
                                      actions

  Integrations                        Gmail and other explicitly
                                      configured services

  Plugins                             Extensible skills with permissions
                                      and staging

  Security                            Credential storage, permission
                                      checks, audit events, and redaction
  -----------------------------------------------------------------------

### Technology direction

Choose libraries during implementation based on current compatibility
and licensing. Candidate technologies include:

-   Python 3.11 or newer (select and pin a version after dependency
    testing).
-   CustomTkinter or another suitable Python desktop UI framework.
-   SQLite for local structured memory.
-   Windows Credential Manager through a secure keyring library for
    secrets.
-   Faster-Whisper or another supported speech-recognition engine.
-   Piper or Windows speech APIs for speech output.
-   A wake-word engine such as Porcupine, subject to its current
    licensing and usage terms.
-   Playwright for supported browser automation.
-   PyWinAuto or carefully scoped Windows automation tools for desktop
    control.

These are candidate choices, not mandatory dependencies. Confirm
platform support, licensing, and maintenance status before adopting
them.

## Requirements

### Target environment

-   Windows 10 or Windows 11.
-   Python version selected by the project and recorded in its
    dependency files.
-   Internet access for cloud providers and online integrations.
-   Optional microphone and speakers/headset for voice features.
-   Optional local model runtime (for example, Ollama or LM Studio) if
    local inference is desired.

Hardware requirements depend on the selected speech models, local
language models, and automation workloads. The initial application
should remain useful in text-only mode on modest hardware.

## Getting started

The complete development specification is in
**[`JARVIS_Project_Context.md`](JARVIS_Project_Context.md)**. Treat that
file as the canonical source of requirements and confirmed preferences.

### 1. Prepare the environment

Install a supported Python version, then open PowerShell in the
repository directory:

``` powershell
py --version
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

If PowerShell blocks activation, consult Microsoft's execution-policy
guidance or activate the environment using the appropriate command for
your shell. Do not weaken system security settings globally just to
activate a virtual environment.

### 2. Install project dependencies

Phase 1 created `requirements.txt` with pinned, verified versions. Install
them into the virtual environment:

``` powershell
python -m pip install -r requirements.txt
```

For development (including tests):

``` powershell
python -m pip install -r requirements-dev.txt
```

The Python version used for the Phase 1 build was **3.14**. If you use a
different version, run the test suite to verify compatibility.

### 3. Configure the application

On first launch, the application should guide the user through setup:

-   Choose text-only, voice-enabled, cloud, local, or hybrid operation.
-   Add an AI provider or local model.
-   Configure a gateway only when needed.
-   Test the connection before activating a provider.
-   Set voice, wake phrase, startup, and standby preferences.
-   Review permissions for integrations and automation.

Do not put real API keys in source code, README files, ordinary
YAML/JSON configuration, screenshots, or logs.

### 4. Run the application

Phase 1 provides a working entry point with validated configuration,
secret-redacting logging, and the dashboard/tray foundation:

``` powershell
# Normal start: dashboard and/or system tray per config/settings.yaml
python main.py

# Headless start (no UI; for testing and service use)
python main.py --headless
```

Run the automated test suite:

``` powershell
python -m pytest
```

GUI behaviour (window layout, tray icon) is verified manually; automated
tests cover configuration, credentials, registries, and log redaction.

## Configuration

The Universal API & Gateway Manager is a core requirement. It should let
the user configure providers without editing application source code.

Each provider configuration should support applicable fields such as:

-   Provider display name and provider type.
-   API key or secure credential reference.
-   Base URL and endpoint path.
-   Gateway URL and gateway-specific settings.
-   Model name or deployment identifier.
-   Authentication method and custom headers.
-   Request timeout and retry policy.
-   Rate limits and usage limits, where known.
-   Enabled/disabled state and connection-test result.

The system should support compatible cloud APIs and local model
endpoints. Provider examples to evaluate include OpenAI-compatible
services, Gemini, Anthropic, Groq, Cerebras, OpenRouter, Ollama, and LM
Studio. Availability, pricing, free-tier limits, endpoint formats, and
terms can change; verify them against each provider's official
documentation.

**Routing rules:** allow task-specific provider/model selection and
user-defined fallbacks. Do not silently send sensitive content to
another cloud provider when a preferred provider fails. Make routing and
data destinations visible to the user.

## Security and approvals

Security is a design requirement, not a later add-on.

-   Store API keys and OAuth tokens in Windows Credential Manager or an
    equivalent secure credential store.
-   Keep only non-secret settings and credential references in ordinary
    configuration files.
-   Redact credentials and sensitive content from logs and diagnostic
    reports.
-   Request explicit approval before sending messages, publishing
    content, deleting or overwriting files, making purchases, or
    performing other consequential actions.
-   Use least-privilege permissions for integrations and automation.
-   Show the user what an action will do before asking for approval.
-   Keep an audit trail of proposed actions, approvals, outcomes, and
    errors without recording secrets.
-   Test risky actions with mocks or sandbox accounts before enabling
    real-world execution.

## Development roadmap

Build in small, testable phases rather than attempting the entire
assistant in one script.

1.  ✅ **Complete (Phase 1).** Project foundation, settings, logging,
    application entry point. See
    [`PROJECT_STATUS.md`](PROJECT_STATUS.md) for details and limitations.
2.  ✅ **Complete (Phase 2).** Provider adapters (OpenAI-compatible,
    Ollama, Gemini, Anthropic), gateway routing, connection testing,
    capability registry, cloud/local/hybrid routing with fallback, text
    conversation and tool calling at the AI layer.
4.  ✅ **Complete (Phase 3).** SQLite memory: conversation/message/task
    persistence, FTS5 full-text search (LIKE fallback), backup/export/
    deletion, persistence across restart, and a live memory-backed chat
    panel.
5.  ⏳ **Early slice done.** Application registry and safe app launcher
    (`config/applications.yaml`, `automation/app_launcher.py`) — registered
    apps (including PowerShell and Command Prompt) open from their
    configured directories; full desktop automation continues in Phase 6.
2.  Universal provider and gateway manager.
3.  AI conversation interface and provider routing.
4.  SQLite memory and retrieval.
5.  Task orchestration, permissions, and approval workflow.
6.  Voice input, wake-word detection, and speech output.
7.  System tray, dashboard, and Windows startup behavior.
8.  Desktop automation and browser research.
9.  Gmail integration using official OAuth/API flows.
10. Additional messaging and productivity integrations.
11. Plugin lifecycle, staging, review, and installation approval.
12. Security hardening, tests, packaging, and release.

Each phase should include working code, tests, updated documentation,
and a clear record of what is complete and what remains.

## Project structure

The implementation may evolve, but a modular layout is recommended:

``` text
JARVIS/
├── README.md
├── JARVIS_Project_Context.md
├── pyproject.toml
├── requirements.txt
├── .gitignore
├── core/
├── providers/
├── gateway/
├── voice/
├── memory/
├── automation/
├── integrations/
│   ├── browser/
│   └── gmail/
├── research/
├── plugins/
├── interface/
├── security/
├── data/
├── logs/
└── tests/
```

Keep generated data, databases, logs, tokens, and local settings out of
version control. The actual implementation should define and document
its final directory layout.

## Testing

At minimum, test:

-   Provider configuration validation and connection tests.
-   Gateway URL, endpoint, authentication, and timeout handling.
-   Provider switching, fallback behavior, and quota/error handling.
-   Confirmation prompts and permission enforcement.
-   Credential redaction in logs.
-   Memory persistence and retrieval.
-   Voice and text operation independently.
-   Startup, standby, wake phrase, and shutdown behavior.
-   Plugin staging and approval.
-   Integrations using mocks or sandbox accounts before live use.

A feature is not complete merely because it runs once. Include error
handling, tests, and user-facing documentation.

## Documentation

-   **[`JARVIS_Project_Context.md`](JARVIS_Project_Context.md):**
    canonical requirements, architecture, preferences, and
    implementation instructions.
-   **[`PROJECT_STATUS.md`](PROJECT_STATUS.md):** concise, honest status
    of completed features, tests, and known limitations.
-   **`README.md`:** project overview and setup guide (this file).
-   Add focused documentation as features are implemented, especially
    provider setup, security, integrations, permissions, and
    troubleshooting.

## Contributing

For every change:

1.  Keep modules focused and interfaces documented.
2.  Avoid hard-coding providers, credentials, local paths, or user
    preferences.
3.  Add or update tests.
4.  Update the README and relevant configuration examples.
5.  Never commit API keys, OAuth tokens, personal data, databases, or
    private logs.
6.  Do not enable consequential automation by default.
7.  Clearly label incomplete features and experimental integrations.

------------------------------------------------------------------------

**Guiding principle:** JARVIS should be customizable and capable, while
keeping the user informed and in control.
