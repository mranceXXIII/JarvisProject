# JARVIS Personal AI --- Project Context File

**Purpose:** This document is the canonical context and development
specification for building a personal AI desktop assistant named JARVIS.

**Target platform:** Windows 10/11\
**Primary language:** Python\
**Architecture:** Modular, plugin-based, hybrid AI,
provider-independent\
**Interaction:** Voice and text\
**Interface:** Background system-tray application and desktop dashboard\
**Autonomy:** Approval-first for important or sensitive actions\
**AI configuration:** User-editable providers, APIs, gateways, models,
and routing rules

------------------------------------------------------------------------

## 1. Project vision

Build a functional personal AI desktop assistant, not merely a chatbot.
JARVIS should understand natural-language instructions, plan tasks, use
approved tools, control desktop applications, research the web, interact
with connected services, generate files, and retrieve relevant past
conversations and work.

The system should be extensible. Adding a new capability should normally
mean adding or enabling a plugin, not rewriting the core application.

The user should be able to turn on Windows, have JARVIS start quietly in
the background, and activate it by saying a configurable wake phrase
such as **"Hey JARVIS"** or by using a manual button, keyboard shortcut,
or dashboard text input.

## 2. Confirmed user preferences

-   **AI setup:** Hybrid. Prefer free and open-source tools where
    practical, with optional paid cloud APIs for advanced capabilities.
    Support local AI where the computer has sufficient resources.
-   **Interaction:** Both voice and text.
-   **Interface:** Both a background/system-tray assistant and a full
    desktop dashboard.
-   **Autonomy:** Approval-first. JARVIS may plan and prepare tasks, but
    must request approval before important or sensitive actions.
-   **Operating system:** Windows 10/11.
-   **Customization:** API providers, gateways, models, application
    paths, wake phrase, voice, workflows, plugins, and permissions
    should be configurable without editing core Python source code.
-   **Memory:** Persist conversations, requests, responses, generated
    content references, task outcomes, preferences, and project history
    locally by default.

## 3. Core operating flow

1.  Windows starts and launches JARVIS.
2.  JARVIS starts minimized in the system tray.
3.  Only lightweight standby components initialize.
4.  A local wake-word engine waits for the configured phrase.
5.  The user activates JARVIS by voice, dashboard, or shortcut.
6.  JARVIS receives a voice or text request.
7.  The assistant retrieves relevant memory when useful.
8.  The AI planner identifies the required tools and creates an
    execution plan.
9.  The permission system evaluates the proposed actions.
10. JARVIS asks for approval where required.
11. Approved tools execute through controlled Python interfaces.
12. JARVIS verifies results, reports success or failure, and records the
    interaction.
13. After a configurable inactivity period, JARVIS returns to standby.

The text interface must work without wake-word activation. The dashboard
may be minimized or closed while the background assistant remains
active, subject to user settings.

## 4. System architecture

Use distinct layers with clear interfaces:

### 4.1 User interface layer

-   Voice activation and voice interaction.
-   Text chat.
-   Desktop dashboard.
-   System tray controls.
-   Approval dialogs.
-   Settings and plugin management.

### 4.2 AI layer

-   Cloud AI providers.
-   Optional local AI providers.
-   Provider-independent model interface.
-   Intent interpretation.
-   Task planning.
-   Tool/function calling where supported.
-   Response generation.
-   Provider routing and fallback.

### 4.3 Task orchestration layer

-   Task planner.
-   Tool registry.
-   Permission checks.
-   Approval manager.
-   Task executor.
-   Progress reporting.
-   Cancellation and timeout handling.
-   Result verification.
-   Error recovery.

### 4.4 Capability layer

-   Desktop automation.
-   File management.
-   Browser automation.
-   Web research.
-   Gmail.
-   Messaging integrations.
-   Calendar and productivity integrations.
-   Custom plugins and workflows.

### 4.5 Memory and security layer

-   SQLite conversation and task storage.
-   Full-text and optional semantic retrieval.
-   File references and generated artifact metadata.
-   Credential management.
-   Permission policies.
-   Audit logs.
-   Backups and data export/deletion.

## 5. Universal API and gateway manager --- mandatory core feature

JARVIS must be provider-independent and gateway-independent wherever
compatible interfaces permit. Do not hardcode a dependency on OpenAI or
any single paid provider.

Create a dedicated **API & Gateway Settings** area in the dashboard and
a provider/gateway management subsystem.

### 5.1 Provider support

Provide adapters or compatible interfaces for: - OpenAI. - Google
Gemini. - Anthropic. - Groq. - Cerebras. - OpenRouter. - Ollama. - LM
Studio. - Other OpenAI-compatible APIs. - Custom providers through
adapter plugins.

Provider names are examples, not guarantees of current free-tier
availability. Free access, quotas, models, rate limits, and terms can
change. Verify current official provider documentation during
implementation.

### 5.2 Manually configurable provider fields

Where supported by a provider, allow the user to configure: - Provider
name and type. - API key or secure credential reference. - API base
URL. - Endpoint path. - Model name. - Authentication method. - Custom
request headers. - Request timeout. - Retry policy. - Rate limits and
usage limits. - Supported model parameters such as temperature and token
limits. - Provider-specific options. - Enabled/disabled status.

The dashboard must allow the user to add, edit, test, activate,
deactivate, and remove providers without changing core Python source
code.

### 5.3 Gateway configuration

Allow gateways to be configured independently of providers. Support: -
Direct provider connections. - Custom API gateways. - Reverse proxies. -
OpenAI-compatible gateways. - Self-hosted gateways. - Local AI gateways.

Where applicable, configure gateway name, URL, API path, authentication,
credential reference, custom headers, timeout, status, and associated
providers.

Allow switching between direct provider access and gateway-based access.
Do not assume all gateways or providers share identical protocols.

### 5.4 Connection testing

Provide a **Test Connection** action that makes a minimal safe request
and reports: - Network connectivity. - Authentication result. - Endpoint
compatibility. - Model availability. - Supported capabilities where
discoverable. - Useful error details without exposing secrets.

Saving a configuration must not be represented as proof that it works. A
provider becomes active only after validation or an explicit user
override with a clear warning.

### 5.5 Free-tier and local AI support

Free-tier APIs must be first-class configuration options. Do not require
a paid subscription to a particular provider. Allow manual entry of
free-tier API keys, URLs, and model names.

Respect provider quotas, rate limits, terms, and usage restrictions. Do
not describe a service as unlimited or free unless verified.

Support local model runtimes such as Ollama and LM Studio. Local models
may be used for offline tasks or privacy-sensitive processing when
appropriate and capable.

### 5.6 Provider routing and fallback

Allow different providers for different task categories, for example: -
General conversation. - Complex reasoning. - Coding assistance. -
Research synthesis. - Local/offline tasks. - Privacy-sensitive tasks.

Support user-selected providers and configurable automatic routing.

Allow a fallback chain, such as: 1. Preferred free-tier provider. 2.
Another configured provider. 3. Local model.

Only fall back to a provider that supports the required task
capabilities. Do not silently move sensitive content to a different
external provider. Ask permission if the fallback would disclose private
information to another service.

### 5.7 Capability registry

Each provider/model adapter must declare supported features, such as: -
Text generation. - Streaming. - Tool/function calling. - Structured
output. - Image input. - Audio input/output. - Context limits, if
known. - Usage reporting, if supported.

The planner must not request unsupported capabilities. Clearly report
unsupported features rather than pretending they work.

### 5.8 Hot reload and safe changes

Apply validated provider and gateway settings without reinstalling
JARVIS. Do not interrupt in-flight tasks unexpectedly. Back up
configuration before changes and roll back invalid settings.

### 5.9 Credential security

Never store real API keys in ordinary YAML/JSON configuration files or
source control. Use Windows Credential Manager or a suitable secure
credential store, with Python `keyring` where appropriate. Configuration
files should store secret references, not secret values.

Never expose credentials in logs, error messages, screenshots, reports,
or the dashboard. Mask keys in the UI. Support independent credential
replacement and revocation.

## 6. AI engine

Implement a provider-independent AI router and adapter interface. Use
the current supported API and SDK documentation for each provider.

The AI engine must: - Understand natural-language requests. - Ask
clarifying questions when needed. - Break complex tasks into steps. -
Select tools from an explicit registry. - Produce structured tool
requests. - Handle provider errors and rate limits. - Support
configurable cloud-only, local-only, and hybrid modes. - Respect privacy
and routing settings. - Avoid claiming actions succeeded before
verification.

Cloud AI should not receive unrestricted computer control. The model
proposes tool calls; local Python validates permissions and executes
approved operations.

## 7. Voice system

Use a configurable local wake-word engine such as Picovoice Porcupine,
subject to current Windows and licensing requirements.

Implement: - Configurable wake phrase, default "Hey JARVIS". - Local
standby wake-word detection. - Microphone selection and sensitivity
settings where supported. - Speech-to-text using Faster-Whisper or
another configurable engine. - Text-to-speech using Piper, Windows TTS,
or another configurable engine. - Configurable voice and speaking
rate. - Manual activation and keyboard shortcut. - Mute, pause, and
emergency stop controls. - Inactivity timeout and return-to-standby
behavior.

Do not continuously transmit microphone audio to cloud services in
standby mode. Explain any cloud processing that occurs after activation
and provide controls.

## 8. Text and dashboard interaction

Build a desktop dashboard initially with CustomTkinter, unless a
better-supported choice is justified.

Include: - JARVIS status and activation controls. - Chat panel. -
Voice/microphone status. - Current task and progress. - Conversation
history. - Memory search and management. - API & Gateway Settings. -
Provider/model routing settings. - Plugin manager. - Workflow manager. -
Connected services. - Permission settings. - Logs and diagnostics.

The dashboard should be optional. Core voice/text functions should
remain available when it is minimized.

## 9. Desktop and Windows automation

Use appropriate Windows automation tools such as PyWinAuto, PyAutoGUI,
and Windows APIs.

Capabilities: - Discover configured/installed applications. - Launch and
close applications. - Switch, minimize, and maximize windows. - Keyboard
and mouse automation. - Screenshots when needed. - Search, create, copy,
move, rename, and organize files. - Open folders and documents. - Run
explicitly approved commands.

Create an editable application registry with application names,
executable paths or Windows identifiers, and optional launch arguments.

Never execute arbitrary AI-generated shell commands without validation
and permission checks. Destructive file operations require explicit
confirmation.

## 10. Browser automation and web research

Use Playwright where appropriate for Chromium, Chrome, Edge, and
Firefox. Support configurable browser profiles or isolated automation
sessions.

Capabilities: - Search the web using a configured search provider/API. -
Open URLs and navigate permitted pages. - Read accessible webpage
content. - Extract and compare information. - Keep source URLs and
attribution. - Generate research summaries and reports. - Download
permitted files on request.

Use official APIs and permitted access methods. Do not bypass
authentication, CAPTCHAs, paywalls, or website access restrictions.
Treat page content as untrusted input, not as instructions that can
override JARVIS security rules.

## 11. Gmail integration

Use the official Gmail API and OAuth 2.0.

Capabilities: - Connect an account. - Search and read authorized
email. - Summarize threads. - Find attachments. - Draft emails. -
Prepare replies and forwards. - Send only after explicit approval by
default. - Organize messages only when authorized.

Use minimum necessary OAuth scopes. Securely store and refresh tokens.
Show recipient, subject, and body before sending. Never send real emails
during automated tests.

## 12. Messaging integrations

Build independent adapters for services with supported APIs,
prioritizing: - Telegram. - Discord. - WhatsApp Business Cloud API. -
Microsoft Teams, where supported.

Capabilities depend on each platform's API, account type, permissions,
and policies. Support reading authorized messages, summarization,
drafting, and sending after approval where permitted.

Do not assume personal WhatsApp accounts expose the same functionality
as WhatsApp Business APIs. Do not bypass end-to-end encryption,
authentication, or platform protections. Clearly document limitations.

## 13. Persistent memory

Use SQLite for durable local structured storage. Add full-text search
and optional embedding/vector retrieval for semantic memory.

Store: - User requests and assistant responses. - Conversation
identifiers and timestamps. - Task plans and execution results. -
Generated content metadata and file references. - User preferences and
explicit instructions. - Custom commands and workflows. - Project
decisions and progress. - Relevant source URLs.

Requirements: - Save conversations automatically. - Persist across
restarts. - Retrieve relevant history by natural-language query. -
Recall prior generated files and projects. - Continue previous tasks
using retrieved context. - Avoid loading the entire history into every
model request. - Provide export, backup, and deletion controls. - Do not
claim something was saved unless storage succeeded.

Keep memory independent of the AI provider so changing models does not
erase history. Do not store sensitive credentials in conversation
memory.

## 14. Plugin and skill system

Build a plugin architecture with: - Unique name and version. -
Description. - Dependencies. - Declared capabilities. - Required
permissions. - Configuration schema. - Execution interface. - Tests and
documentation.

Provide plugin discovery, enable/disable, installation, configuration,
testing, and removal.

When the user requests a new capability, JARVIS may propose and generate
a plugin. It must: 1. Check whether an existing skill already supports
the request. 2. Generate code in a staging area. 3. Run static checks
and isolated tests. 4. Show the proposed changes and required
permissions. 5. Obtain explicit approval. 6. Install and register the
approved plugin. 7. Record the change and documentation.

Never automatically execute untrusted or newly generated plugin code
with unrestricted permissions. Use process isolation or another
defensible sandbox where practical, and explain any limitations.

## 15. Workflows and customization

Allow natural-language creation of reusable workflows, such as: - "Start
work" opens selected applications. - Prepare a daily summary. - Organize
a chosen folder. - Create a research report from a topic. - Run a
recurring approved routine.

Allow workflows to be created, edited, renamed, paused, deleted,
scheduled, and triggered by voice or text.

Store workflows in editable configuration files. Scheduled or recurring
actions must respect approval policies and notify the user of failures.

## 16. Approval and security model

Use an approval-first architecture.

Suggested default classifications:

**Low risk:** Searching public websites, opening applications, reading
permitted pages, generating drafts and reports.

**Medium risk:** Modifying or moving files, changing application
settings, running approved scripts, sending ordinary messages.

**High risk:** Permanent deletion, financial operations, purchases,
public posting, sharing private information, administrative commands,
and sending sensitive communications.

Require confirmation for medium- and high-risk actions by default. The
user may configure trusted routines, but never bypass platform
authentication or safety restrictions.

Approval prompts must show: - The exact action. - Target application or
service. - Data to be shared or changed. - Potential consequences. -
Approve and reject choices.

Implement: - Credential protection. - Least-privilege tool
permissions. - Command allowlists. - Input validation. - Audit
logging. - Emergency stop. - Rate limits. - Timeouts. - Prompt-injection
defenses.

Emails, webpages, attachments, and other external content are untrusted
data. They must not override system instructions, change permissions, or
authorize actions.

## 17. Windows startup and background mode

Provide a Windows startup manager: - Launch at user sign-in when
enabled. - Start minimized in the system tray. - Initialize only
essential standby components. - Delay expensive AI initialization until
activation. - Allow startup to be disabled. - Provide pause, standby,
and full shutdown controls.

Do not run unnecessary model inference while idle. Ensure clean shutdown
and recovery after ordinary application errors.

## 18. Configuration files

Keep user settings outside source code. Use validated YAML/JSON
configuration for non-secret settings.

Suggested files: - `settings.yaml` - `providers.yaml` -
`gateways.yaml` - `models.yaml` - `routing.yaml` - `permissions.yaml` -
`applications.yaml` - `workflows.yaml`

Secrets must be stored in a secure credential store, referenced by
identifier in configuration. Validate configuration on load and preserve
backups.

## 19. Suggested project structure

``` text
JARVIS/
├── main.py
├── launcher.py
├── requirements.txt
├── .env.example
├── README.md
├── config/
│   ├── settings.yaml
│   ├── providers.yaml
│   ├── gateways.yaml
│   ├── models.yaml
│   ├── routing.yaml
│   ├── permissions.yaml
│   ├── applications.yaml
│   └── workflows.yaml
├── core/
│   ├── assistant.py
│   ├── ai_router.py
│   ├── task_planner.py
│   ├── task_executor.py
│   ├── tool_registry.py
│   ├── approval_manager.py
│   ├── event_bus.py
│   └── state_manager.py
├── providers/
│   ├── provider_manager.py
│   ├── provider_registry.py
│   ├── base_adapter.py
│   ├── openai_compatible.py
│   ├── gemini_adapter.py
│   ├── anthropic_adapter.py
│   ├── ollama_adapter.py
│   └── custom_adapter.py
├── gateway/
│   ├── gateway_manager.py
│   ├── endpoint_router.py
│   ├── connection_tester.py
│   ├── fallback_manager.py
│   └── usage_monitor.py
├── voice/
│   ├── wake_word.py
│   ├── microphone.py
│   ├── speech_to_text.py
│   └── text_to_speech.py
├── memory/
│   ├── database.py
│   ├── conversation_store.py
│   ├── memory_retrieval.py
│   ├── embeddings.py
│   └── backup.py
├── automation/
│   ├── app_launcher.py
│   ├── window_manager.py
│   ├── keyboard_mouse.py
│   ├── file_manager.py
│   └── command_runner.py
├── integrations/
│   ├── browser/
│   ├── gmail/
│   ├── telegram/
│   ├── discord/
│   ├── whatsapp/
│   └── calendar/
├── research/
│   ├── search_engine.py
│   ├── webpage_reader.py
│   └── research_report.py
├── plugins/
│   ├── builtin/
│   ├── custom/
│   └── plugin_manager.py
├── interface/
│   ├── dashboard.py
│   ├── chat_panel.py
│   ├── settings_panel.py
│   ├── api_gateway_panel.py
│   ├── approval_dialog.py
│   └── system_tray.py
├── security/
│   ├── credential_manager.py
│   ├── permission_checker.py
│   ├── action_validator.py
│   └── audit_logger.py
├── data/
│   ├── backups/
│   └── generated/
├── logs/
└── tests/
```

The structure may evolve during development, but preserve modular
boundaries and document changes.

## 20. Development phases

Build incrementally and test each phase before proceeding.

### Phase 1 --- Foundation and configuration

-   Create the project and virtual environment.
-   Add logging and validated configuration.
-   Build provider/gateway interfaces and API settings early.
-   Implement secure credential references.
-   Build a basic dashboard and system tray foundation.
-   Add tests for configuration and secret masking.

### Phase 2 --- API manager and AI brain

-   Implement provider adapters.
-   Add custom OpenAI-compatible endpoint support.
-   Add gateway routing.
-   Add connection testing.
-   Add model capability registry.
-   Add cloud/local/hybrid routing.
-   Add fallback and quota/error handling.
-   Implement text conversation and tool calling.

### Phase 3 --- Memory

-   Implement SQLite.
-   Save conversations and task outcomes.
-   Add full-text search and optional semantic retrieval.
-   Add backup/export/deletion.
-   Verify persistence after restart.

### Phase 4 --- Task orchestration and approvals

-   Implement tool registry.
-   Implement task planning and execution.
-   Add permission checks and approval dialogs.
-   Add cancellation, timeouts, logs, and verification.

### Phase 5 --- Voice

-   Add wake-word detection.
-   Add speech recognition and synthesis.
-   Add standby/active state transitions.
-   Test microphone privacy controls.

### Phase 6 --- Desktop automation

-   Add application registry and launcher.
-   Add window control.
-   Add file operations.
-   Add safe command execution.

### Phase 7 --- Browser and research

-   Add browser automation.
-   Add search provider integration.
-   Add webpage extraction and source tracking.
-   Generate sourced reports.

### Phase 8 --- Gmail

-   Configure Google Cloud and OAuth.
-   Add search, read, summarize, draft, and approved send.
-   Test with a dedicated account or mocks.

### Phase 9 --- Messaging

-   Add supported platform adapters.
-   Document API and account limitations.
-   Test with test accounts and mocks.

### Phase 10 --- Plugins and workflows

-   Add plugin discovery and lifecycle.
-   Add staged generation and isolated testing.
-   Add user-approved installation.
-   Add reusable custom workflows.

### Phase 11 --- Security and reliability

-   Test permissions and approval enforcement.
-   Test prompt-injection resistance.
-   Test secret handling.
-   Test provider failures and fallback.
-   Test database backups and recovery.

### Phase 12 --- Windows integration and release

-   Add startup configuration.
-   Finalize system tray and dashboard.
-   Optimize idle resource usage.
-   Package the application.
-   Complete documentation and acceptance tests.

## 21. Testing and acceptance criteria

Use automated tests and mocks wherever possible. Do not send real
emails, messages, purchases, public posts, or destructive file
operations during automated tests.

At minimum, verify:

1.  JARVIS launches and shuts down cleanly.
2.  Dashboard and text interaction work.
3.  Voice wake-word activation works on the target hardware.
4.  API providers can be added, edited, tested, activated, and removed.
5.  Custom base URLs, endpoints, models, and gateways can be configured.
6.  Credentials never appear in logs or ordinary configuration files.
7.  Provider capability checks prevent unsupported tool use.
8.  Fallback works only for compatible tasks.
9.  Sensitive data is not silently rerouted to another external
    provider.
10. Conversation history persists after restart.
11. Relevant prior conversations can be retrieved.
12. Desktop tools obey permissions.
13. Browser research retains source URLs.
14. Gmail drafts and approvals work.
15. Messaging adapters respect platform limitations.
16. Plugins are staged, tested, and approved before installation.
17. Windows startup and standby behavior work.
18. Failures are logged without exposing private information.

A feature is complete only when implemented, tested, documented, and its
limitations are stated honestly.

## 22. Coding agent instructions

Start with Phase 1. Do not generate the entire project in one enormous
response.

Before coding: 1. Explain the architecture and choices. 2. Check current
official documentation for selected libraries and APIs. 3. Identify
required accounts, credentials, and potential costs. 4. Provide Windows
PowerShell setup commands. 5. Create the initial folder structure. 6.
Create complete, runnable source files. 7. Add tests and run them. 8.
Explain how to launch and verify the application. 9. Update the README
and development checklist.

Use pinned, compatible dependencies. Prefer maintained libraries. Do not
invent API endpoints, free-tier quotas, or unsupported provider
features.

When a requested integration requires a key, account, or permission,
explain how to obtain it and keep it optional until configured.

Do not claim a feature is complete when it is a placeholder.

Maintain a concise project status document listing: - Completed
features. - Current phase. - Files created or changed. - Tests passed
and failed. - Known limitations. - Next tasks.

## 23. Final mission

Build a personal JARVIS assistant that becomes a useful part of the
user's Windows workflow.

The user should be able to start the computer, let JARVIS enter quiet
standby, say "Hey JARVIS" or type a request, and have JARVIS understand,
plan, request approval when needed, execute through controlled tools,
verify the result, and remember the interaction.

The user must be able to change API providers, use free-tier APIs
manually, edit gateway URLs, change models, configure local AI, and add
approved skills without rewriting the core application.

**Begin with Phase 1 and build the system incrementally.**
