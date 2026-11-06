# Plugins and Workflows Guide — JARVIS Phase 10

## Part A — Plugins

Plugins add new tools to JARVIS. Lifecycle: **staged → validated → approved
→ installed → (enabled/disabled)**.

### Folder layout

```text
plugins/
├── custom/          # installed plugins live here
│   └── my_plugin/
│       ├── manifest.json
│       └── plugin.py
└── staging/         # generated/not-yet-approved plugins (gitignored)
```

### manifest.json

```json
{
  "name": "my_plugin",
  "version": "1.0.0",
  "description": "What this plugin does",
  "author": "you",
  "permissions": [],
  "entry": "plugin.py",
  "enabled": true
}
```

`permissions` declares elevated capabilities the code uses. The static
analyzer (AST-based) detects these automatically and **refuses installation
until every used capability is declared**:

| Permission | Meaning | Detected via |
|---|---|---|
| `process` | run external programs | `subprocess`, `os.system`, `os.popen` |
| `network` | make network connections | `socket`, `requests`, `urllib` |
| `filesystem_write` | write files | `shutil`, `pathlib`, `open` |
| `code_execution` | dynamic code execution | `eval`, `exec`, `compile` |

### plugin.py contract

The entry file must define:

```python
def register(registry) -> None:
    registry.register(
        ToolDefinition(name="my_plugin_tool", description="...", risk="low",
                       parameters={...}),
        executor_function,
    )
```

Plugin tools join the same registry as built-ins — they pass through the
permission checker, approval dialogs, and the audit trail like everything
else.

### The flow (chat or code)

1. **Generate a skeleton:** `plugin_generate(name="my_plugin",
   description="...")` — creates staged files.
2. **Edit** `plugins/staging/my_plugin/plugin.py` (or ask JARVIS to).
3. **Validate:** `plugin_validate(name="my_plugin")` — static safety checks.
4. **Install:** `plugin_approve_install(name="my_plugin")` — shows the
   plugin and its declared permissions and **asks for explicit approval**.
5. **Disable/enable:** `plugin_toggle(name="my_plugin", enabled=false)`.

> **Honest limitation:** plugin code runs in-process. The staged analysis +
> approval + risk-gated tools provide defense in depth, but there is no
> OS-level sandbox. Only install plugins you have read.

## Part B — Workflows

Workflows are named sequences of tool calls in
**`config/workflows.yaml`** (human-editable).

```yaml
workflows:
  - name: start_work
    description: Show time and list applications
    steps:
      - tool: get_current_time
        arguments: {}
      - tool: list_applications
        arguments: {}
  - name: morning_briefing
    schedule: "0 8 * * *"   # RESERVED for Phase 12 scheduled runs
    steps:
      - tool: get_current_time
        arguments: {}
```

### Tools

| Tool | Risk | Behaviour |
|---|---|---|
| `workflow_list` | low | List workflows |
| `workflow_run` | low | Run by name — **each step still hits its own approval gates** |
| `workflow_save` | medium | Create a workflow (steps validated against the registry) |
| `workflow_delete` / `workflow_pause` | medium | Remove / pause-resume |

### Example chat flows

- *"run workflow start_work"* → runs the steps (approvals per step as needed)
- *"create a workflow called standup with steps get_current_time;
  take_screenshot"* → created (medium risk → approval to save)
- *"delete the workflow standup"*

### Scheduling note (honest)

The `schedule` field is stored and surfaced, but **scheduled execution is
Phase 12 work** — workflows currently run on demand only.
