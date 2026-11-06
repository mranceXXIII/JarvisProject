"""Plugin lifecycle manager (spec section 14).

Lifecycle: staged -> validated -> approved -> installed -> (enabled|disabled).

Safety model:
- A plugin is a folder with ``manifest.json`` and an entry Python file.
- Staged plugins are NEVER imported. Static AST analysis lists the
  capabilities the code uses (subprocess, network, filesystem writes,
  eval/exec); every capability must be declared in the manifest's
  ``permissions`` before installation can be approved.
- Installation requires explicit user approval showing the plugin and its
  declared permissions.
- Only installed + enabled plugins are imported at startup; their tools
  join the normal registry and therefore the permission/approval/audit
  pipeline.
- Honest limitation: plugin code runs in-process (no OS-level sandbox).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Callable

from core.tool_registry import ToolRegistry
from security.audit_logger import AuditLogger

logger = logging.getLogger("jarvis.plugins")

CUSTOM_DIR = "custom"
STAGING_DIR = "staging"

# Capability -> AST indicators that reveal its use.
CAPABILITY_INDICATORS: dict[str, tuple[str, ...]] = {
    "process": ("subprocess", "os.system", "os.popen"),
    "network": ("socket", "urllib.request", "requests", "httpx"),
    "filesystem_write": ("shutil", "pathlib", "open"),
    "code_execution": ("eval", "exec", "__import__", "compile"),
}

PERMISSION_DESCRIPTIONS = {
    "process": "run external programs",
    "network": "make network connections",
    "filesystem_write": "write files",
    "code_execution": "dynamically execute generated code",
}


class PluginError(RuntimeError):
    """Raised for plugin lifecycle problems."""


class PluginManifest:
    """Parsed manifest.json (kept dict-based for forward compatibility)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.name = str(data.get("name", "")).strip()
        self.version = str(data.get("version", "0.0.1"))
        self.description = str(data.get("description", ""))
        self.author = str(data.get("author", ""))
        self.permissions = [str(p) for p in data.get("permissions", [])]
        self.entry = str(data.get("entry", "plugin.py"))
        self.enabled = bool(data.get("enabled", True))

    @classmethod
    def load(cls, path: Path) -> "PluginManifest":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PluginError(f"invalid manifest {path}: {exc}") from exc
        manifest = cls(data)
        problems = manifest.validate()
        if problems:
            raise PluginError(f"invalid manifest {path}: " + "; ".join(problems))
        return manifest

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.name:
            problems.append("missing 'name'")
        elif not self.name.replace("_", "").isalnum():
            problems.append(
                f"invalid plugin name '{self.name}' (letters/digits/underscore only)"
            )
        for permission in self.permissions:
            if permission not in CAPABILITY_INDICATORS:
                problems.append(f"unknown permission '{permission}'")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "permissions": self.permissions,
            "entry": self.entry,
            "enabled": self.enabled,
        }


def analyze_source(source: str) -> set[str]:
    """AST analysis: which declared capabilities does the code use?"""
    required: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise PluginError(f"plugin source has a syntax error: {exc}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                required.update(_capability_for(alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                required.update(_capability_for(node.module))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("eval", "exec", "compile", "__import__"):
                required.add("code_execution")
    return required


def _capability_for(module_name: str) -> set[str]:
    root = module_name.split(".")[0]
    found: set[str] = set()
    for capability, indicators in CAPABILITY_INDICATORS.items():
        for indicator in indicators:
            if indicator == root or indicator.startswith(root + "."):
                found.add(capability)
    return found


class PluginManager:
    """Manages staged and installed plugins."""

    def __init__(
        self,
        plugins_dir: Path,
        registry: ToolRegistry,
        audit: AuditLogger,
        approver: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._plugins_dir = plugins_dir
        self._custom_dir = plugins_dir / CUSTOM_DIR
        self._staging_dir = plugins_dir / STAGING_DIR
        self._registry = registry
        self._audit = audit
        # approver(tool, description) -> bool; wired to ApprovalManager in main
        self._approver = approver
        self._disabled: set[str] = set()
        self._custom_dir.mkdir(parents=True, exist_ok=True)
        self._staging_dir.mkdir(parents=True, exist_ok=True)

    def set_approver(self, approver: Callable[[str, str], bool]) -> None:
        self._approver = approver

    # -- staging ----------------------------------------------------------

    def stage_new_plugin(self, name: str, description: str) -> Path:
        """Generate a new plugin skeleton in the staging area."""
        clean = name.strip().lower().replace("-", "_")
        if not clean.isidentifier():
            raise PluginError(f"invalid plugin name '{name}'")
        target = self._staging_dir / clean
        if target.exists():
            raise PluginError(f"staged plugin '{clean}' already exists")
        target.mkdir(parents=True)
        manifest = {
            "name": clean,
            "version": "0.1.0",
            "description": description,
            "author": "generated",
            "permissions": [],
            "entry": "plugin.py",
            "enabled": True,
        }
        (target / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        (target / "plugin.py").write_text(
            _PLUGIN_TEMPLATE.format(
                plugin_module=clean, plugin_description=description
            ),
            encoding="utf-8",
        )
        self._audit.log("plugin_staged", plugin=clean, description=description)
        logger.info("plugin '%s' staged at %s", clean, target)
        return target

    def validate_staged(self, name: str) -> list[str]:
        """Static checks; returns human-readable problems (empty = OK)."""
        staged = self._staging_dir / name
        manifest_path = staged / "manifest.json"
        if not manifest_path.is_file():
            return [f"staged plugin '{name}' has no manifest.json"]
        try:
            manifest = PluginManifest.load(manifest_path)
        except PluginError as exc:
            return [str(exc)]
        entry = staged / manifest.entry
        if not entry.is_file():
            return [f"entry file '{manifest.entry}' missing"]
        try:
            source = entry.read_text(encoding="utf-8")
            used = analyze_source(source)
        except PluginError as exc:
            return [str(exc)]
        undeclared = used - set(manifest.permissions)
        if undeclared:
            return [
                "code uses undeclared capabilities: "
                + ", ".join(
                    f"{c} ({PERMISSION_DESCRIPTIONS.get(c, c)})"
                    for c in sorted(undeclared)
                )
                + " - declare them in manifest.json permissions, then re-approve"
            ]
        return []

    # -- approval and installation ------------------------------------------

    def install_staged(self, name: str) -> str:
        """Validate, get explicit approval, then install a staged plugin."""
        problems = self.validate_staged(name)
        if problems:
            raise PluginError(
                f"plugin '{name}' failed validation: " + "; ".join(problems)
            )
        manifest = PluginManifest.load(self._staging_dir / name / "manifest.json")
        description = (
            f"Install plugin '{manifest.name}' v{manifest.version}. "
            f"Description: {manifest.description}. Declared permissions: "
            f"{', '.join(manifest.permissions) or 'none (pure registry tools)'}."
        )
        if self._approver is None:
            raise PluginError(
                "no approval handler available; plugin installation denied"
            )
        if not self._approver("plugin_install", description):
            self._audit.log("plugin_install_denied", plugin=name)
            return f"Installation of plugin '{name}' was denied."
        staged = self._staging_dir / name
        installed = self._custom_dir / name
        if installed.exists():
            raise PluginError(f"installed plugin '{name}' already exists")
        shutil.move(str(staged), str(installed))
        self._audit.log(
            "plugin_installed",
            plugin=manifest.name,
            version=manifest.version,
            permissions=manifest.permissions,
        )
        self.load_installed_plugin(installed)
        return f"Plugin '{manifest.name}' installed and registered."

    # -- installed plugins ----------------------------------------------------

    def list_installed(self) -> list[dict[str, Any]]:
        plugins: list[dict[str, Any]] = []
        for directory in sorted(self._custom_dir.iterdir()):
            manifest_path = directory / "manifest.json"
            if not directory.is_dir() or not manifest_path.is_file():
                continue
            try:
                manifest = PluginManifest.load(manifest_path)
            except PluginError as exc:
                plugins.append({"name": directory.name, "error": str(exc)})
                continue
            plugins.append(
                {
                    **manifest.to_dict(),
                    "disabled_by_user": manifest.name in self._disabled,
                }
            )
        return plugins

    def load_installed_plugins(self) -> int:
        """Import and register every installed + enabled plugin."""
        count = 0
        for directory in sorted(self._custom_dir.iterdir()):
            manifest_path = directory / "manifest.json"
            if not directory.is_dir() or not manifest_path.is_file():
                continue
            if self.load_installed_plugin(directory):
                count += 1
        return count

    def load_installed_plugin(self, directory: Path) -> bool:
        """Import one plugin and call its register() unless disabled."""
        try:
            manifest = PluginManifest.load(directory / "manifest.json")
        except PluginError as exc:
            logger.error("skipping plugin %s: %s", directory.name, exc)
            return False
        if not manifest.enabled or manifest.name in self._disabled:
            logger.info("plugin '%s' is disabled; not loaded", manifest.name)
            return False
        entry = directory / manifest.entry
        if not entry.is_file():
            logger.error("plugin '%s' entry missing", manifest.name)
            return False
        try:
            spec = importlib.util.spec_from_file_location(
                f"jarvis_plugin_{manifest.name}", entry
            )
            if spec is None or spec.loader is None:
                raise PluginError("could not create import spec")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            register = getattr(module, "register", None)
            if callable(register):
                register(self._registry)
            self._audit.log("plugin_loaded", plugin=manifest.name)
            logger.info("plugin '%s' loaded", manifest.name)
            return True
        except Exception as exc:
            logger.error("plugin '%s' failed to load: %s", manifest.name, exc)
            self._audit.log(
                "plugin_load_failed", plugin=manifest.name, error=str(exc)
            )
            return False

    def set_enabled(self, name: str, enabled: bool) -> str:
        """Enable or disable a plugin (persisted in its manifest)."""
        manifest_path = self._custom_dir / name / "manifest.json"
        if not manifest_path.is_file():
            raise PluginError(f"installed plugin '{name}' not found")
        manifest = PluginManifest.load(manifest_path)
        manifest.enabled = enabled
        manifest_path.write_text(
            json.dumps(manifest.to_dict(), indent=2), encoding="utf-8"
        )
        if enabled:
            self._disabled.discard(name)
            self.load_installed_plugin(self._custom_dir / name)
            action = "enabled"
        else:
            self._disabled.add(name)
            action = "disabled"
        self._audit.log("plugin_toggled", plugin=name, state=action)
        return f"Plugin '{name}' {action}."


_PLUGIN_TEMPLATE = '''"""JARVIS plugin: {plugin_description}"""

from core.tool_registry import ToolDefinition, ToolExecutionResult


def register(registry) -> None:
    """Register this plugin's tools (low risk by default)."""

    def hello(arguments: dict) -> ToolExecutionResult:
        who = str(arguments.get("who", "world"))
        return ToolExecutionResult(
            tool="{plugin_module}_hello",
            success=True,
            output=f"Hello from plugin, {{who}}!",
        )

    registry.register(
        ToolDefinition(
            name="{plugin_module}_hello",
            description="{plugin_description}",
            risk="low",
            parameters={{
                "who": {{"type": "string", "description": "name to greet"}}
            }},
        ),
        hello,
    )
'''
