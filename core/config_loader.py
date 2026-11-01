"""Validated configuration loading for JARVIS.

Loads `settings.yaml`, `providers.yaml`, and `gateways.yaml` from the config
directory and validates them with Pydantic schemas. Design rules enforced here:

- Secrets are forbidden in configuration files (extra fields such as
  ``api_key`` are rejected). Configuration stores credential *references*
  only (JARVIS_Project_Context.md 5.9).
- A provider cannot be active unless it is enabled; activation additionally
  requires a successful connection test (Phase 2) or explicit user override.
- Loading failures raise :class:`ConfigError` with the offending file and a
  readable reason, so failures are logged without exposing private data.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

SETTINGS_FILE = "settings.yaml"
PROVIDERS_FILE = "providers.yaml"
GATEWAYS_FILE = "gateways.yaml"

# Field names that must never carry secret values in ordinary config files.
FORBIDDEN_SECRET_FIELDS = frozenset(
    {"api_key", "apikey", "secret", "password", "token", "api_secret"}
)


class ConfigError(Exception):
    """Raised when a configuration file is missing or fails validation."""


class AppSettings(BaseModel):
    """Top-level application behaviour settings."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="JARVIS", min_length=1)
    startup_mode: Literal["dashboard", "tray", "both"] = "both"
    dashboard_enabled: bool = True
    tray_enabled: bool = True
    data_dir: str = "data"


class LoggingSettings(BaseModel):
    """Logging behaviour settings."""

    model_config = ConfigDict(extra="forbid")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    file: str = "logs/jarvis.log"
    max_bytes: int = Field(default=1_048_576, gt=0)
    backup_count: int = Field(default=5, ge=0)


class VoiceSettings(BaseModel):
    """Voice subsystem settings (spec section 7). All engines optional."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    wake_phrase: str = "jarvis"
    wake_credential_ref: str = "jarvis/picovoice-access-key"
    input_device: Optional[str] = None
    sample_rate: int = Field(default=16000, gt=0)
    frame_duration: float = Field(default=0.03, gt=0)
    inactivity_timeout_seconds: int = Field(default=120, gt=0)
    stt_model: str = "base"
    tts_enabled: bool = True
    tts_rate: int = Field(default=180, gt=50)


class Settings(BaseModel):
    """Contents of ``settings.yaml``."""

    model_config = ConfigDict(extra="forbid")

    app: AppSettings = Field(default_factory=AppSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    voice: "VoiceSettings" = Field(default_factory=lambda: VoiceSettings())


class ProviderConfig(BaseModel):
    """One AI provider definition from ``providers.yaml``.

    ``credential_ref`` points at an entry in the secure credential store;
    the secret value itself never appears in configuration.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    credential_ref: Optional[str] = None
    base_url: Optional[str] = None
    endpoint_path: Optional[str] = None
    model: Optional[str] = None
    gateway: Optional[str] = None
    enabled: bool = False
    active: bool = False
    timeout_seconds: int = Field(default=30, gt=0)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("extra", mode="before")
    @classmethod
    def _reject_secret_looking_keys(cls, value: Any) -> Any:
        if isinstance(value, dict):
            offending = sorted(FORBIDDEN_SECRET_FIELDS.intersection(value))
            if offending:
                raise ValueError(
                    "secret-like fields are forbidden in config files "
                    f"(found: {', '.join(offending)}); use credential_ref instead"
                )
        return value

    @field_validator("active")
    @classmethod
    def _active_requires_enabled(cls, value: bool, info: Any) -> bool:
        enabled = info.data.get("enabled", False)
        if value and not enabled:
            raise ValueError("a provider cannot be active while it is disabled")
        return value


class GatewayConfig(BaseModel):
    """One gateway definition from ``gateways.yaml``."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    api_path: str = ""
    credential_ref: Optional[str] = None
    enabled: bool = False
    timeout_seconds: int = Field(default=30, gt=0)
    headers: dict[str, str] = Field(default_factory=dict)


class AppConfig(BaseModel):
    """The complete, validated configuration bundle."""

    model_config = ConfigDict(extra="forbid")

    settings: Settings
    providers: tuple[ProviderConfig, ...] = ()
    gateways: tuple[GatewayConfig, ...] = ()
    routing: "RoutingConfig" = Field(default_factory=lambda: RoutingConfig())
    applications: tuple[ApplicationConfig, ...] = ()
    permissions: "PermissionPolicy" = Field(
        default_factory=lambda: PermissionPolicy()
    )
    file_access: "FileAccessConfig" = Field(default_factory=lambda: FileAccessConfig())
    command_runner: "CommandRunnerConfig" = Field(
        default_factory=lambda: CommandRunnerConfig()
    )


class RoutingSettings(BaseModel):
    """AI routing mode settings."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["cloud_only", "local_only", "hybrid"] = "hybrid"


class RouteEntry(BaseModel):
    """A task-category route to a provider."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)


class RoutingConfig(BaseModel):
    """Contents of ``routing.yaml``."""

    model_config = ConfigDict(extra="forbid")

    settings: RoutingSettings = Field(default_factory=RoutingSettings)
    default: RouteEntry | None = None
    routes: dict[str, RouteEntry] = Field(default_factory=dict)
    fallback_chain: list[str] = Field(default_factory=list)
    sensitive_fallback_local_only: bool = True

    @field_validator("routes", mode="before")
    @classmethod
    def _coerce_routes(cls, value: Any) -> Any:
        # Accept the simple YAML form:  category: {provider: name}
        return value or {}


ROUTING_FILE = "routing.yaml"
APPLICATIONS_FILE = "applications.yaml"


class ApplicationConfig(BaseModel):
    """One registered application from ``applications.yaml``.

    Exactly one of ``path`` or (``directory`` + ``executable``) must be
    provided; the directory form restricts lookup to that folder only.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    display_name: str = ""
    path: Optional[str] = None
    directory: Optional[str] = None
    executable: Optional[str] = None
    args: list[str] = Field(default_factory=list)
    working_dir: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)

    @field_validator("aliases")
    @classmethod
    def _validate_aliases(cls, value: list[str]) -> list[str]:
        for alias in value:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", alias):
                raise ValueError(
                    f"invalid alias '{alias}': use letters, digits, '-' or '_'"
                )
        return value

    @model_validator(mode="after")
    def _require_launch_form(self) -> "ApplicationConfig":
        if self.path and (self.directory or self.executable):
            raise ValueError(
                f"application '{self.name}': use either 'path' or "
                "'directory' + 'executable', not both"
            )
        if not self.path and not (self.directory and self.executable):
            raise ValueError(
                f"application '{self.name}': provide 'path', or both "
                "'directory' and 'executable'"
            )
        if self.path and not self.display_name:
            self.display_name = Path(self.path).stem
        return self


def load_application_configs(
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
) -> tuple[ApplicationConfig, ...]:
    """Load and validate all registered applications."""
    path = Path(config_dir) / APPLICATIONS_FILE
    if not path.exists():
        return ()
    payload = _read_yaml(path) or {}
    apps = payload.get("applications", []) if isinstance(payload, dict) else []
    if not isinstance(apps, list):
        raise ConfigError(f"{path.name}: 'applications' must be a list")
    return tuple(_validate_section(path, ApplicationConfig, item) for item in apps)


class PermissionPolicy(BaseModel):
    """Approval policy from ``permissions.yaml`` (spec section 16)."""

    model_config = ConfigDict(extra="forbid")

    require_approval_medium: bool = True
    require_approval_high: bool = True
    trusted_tools: list[str] = Field(default_factory=list)


class FileAccessConfig(BaseModel):
    """File-tool containment rules (spec section 9)."""

    model_config = ConfigDict(extra="forbid")

    allowed_roots: list[str] = Field(
        default_factory=lambda: ["~/Documents", "~/Desktop", "~/Downloads"]
    )
    max_read_bytes: int = Field(default=1_048_576, gt=0)
    max_list_entries: int = Field(default=200, gt=0)


class CommandRunnerConfig(BaseModel):
    """Command allowlist rules (spec section 9)."""

    model_config = ConfigDict(extra="forbid")

    allowed_executables: list[str] = Field(
        default_factory=lambda: ["ipconfig", "ping", "systeminfo"]
    )
    timeout_seconds: int = Field(default=30, gt=0)
    max_output_chars: int = Field(default=4000, gt=0)


class SecurityConfig(BaseModel):
    """All security-related settings from ``permissions.yaml``."""

    model_config = ConfigDict(extra="forbid")

    policy: PermissionPolicy = Field(default_factory=PermissionPolicy)
    file_access: FileAccessConfig = Field(default_factory=FileAccessConfig)
    command_runner: CommandRunnerConfig = Field(default_factory=CommandRunnerConfig)


PERMISSIONS_FILE = "permissions.yaml"


def load_security_config(
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
) -> SecurityConfig:
    """Load and validate the security bundle in ``permissions.yaml``."""
    path = Path(config_dir) / PERMISSIONS_FILE
    if not path.exists():
        return SecurityConfig()
    payload = _read_yaml(path) or {}
    if not isinstance(payload, dict):
        return SecurityConfig()
    return _validate_section(
        path,
        SecurityConfig,
        {
            "policy": payload.get("permissions") or {},
            "file_access": payload.get("file_access") or {},
            "command_runner": payload.get("command_runner") or {},
        },
    )


def load_permission_policy(
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
) -> PermissionPolicy:
    """Backward-compatible loader for the approval policy only."""
    return load_security_config(config_dir).policy


def load_routing_config(config_dir: Path | str = DEFAULT_CONFIG_DIR) -> RoutingConfig:
    """Load and validate ``routing.yaml``."""
    path = Path(config_dir) / ROUTING_FILE
    if not path.exists():
        return RoutingConfig()
    return _validate_section(path, RoutingConfig, _read_yaml(path))


def _read_yaml(path: Path) -> Any:
    """Read a YAML file, raising :class:`ConfigError` on any problem."""
    if not path.exists():
        raise ConfigError(f"configuration file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path.name}: {exc}") from exc


def _validate_section(path: Path, schema: type[BaseModel], payload: Any) -> Any:
    """Validate a YAML section against a Pydantic schema."""
    if payload is None:
        payload = {}
    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration in {path.name}:\n{exc}") from exc


def load_settings(config_dir: Path | str = DEFAULT_CONFIG_DIR) -> Settings:
    """Load and validate ``settings.yaml``."""
    path = Path(config_dir) / SETTINGS_FILE
    return _validate_section(path, Settings, _read_yaml(path))


def load_provider_configs(
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
) -> tuple[ProviderConfig, ...]:
    """Load and validate all provider definitions."""
    path = Path(config_dir) / PROVIDERS_FILE
    payload = _read_yaml(path) or {}
    providers = payload.get("providers", []) if isinstance(payload, dict) else []
    if not isinstance(providers, list):
        raise ConfigError(f"{path.name}: 'providers' must be a list")
    return tuple(_validate_section(path, ProviderConfig, item) for item in providers)


def load_gateway_configs(
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
) -> tuple[GatewayConfig, ...]:
    """Load and validate all gateway definitions."""
    path = Path(config_dir) / GATEWAYS_FILE
    payload = _read_yaml(path) or {}
    gateways = payload.get("gateways", []) if isinstance(payload, dict) else []
    if not isinstance(gateways, list):
        raise ConfigError(f"{path.name}: 'gateways' must be a list")
    return tuple(_validate_section(path, GatewayConfig, item) for item in gateways)


def load_app_config(config_dir: Path | str = DEFAULT_CONFIG_DIR) -> AppConfig:
    """Load and validate the full configuration bundle.

    Raises:
        ConfigError: if any file is missing, unreadable, or fails validation.
    """
    directory = Path(config_dir)
    return AppConfig(
        settings=load_settings(directory),
        providers=load_provider_configs(directory),
        gateways=load_gateway_configs(directory),
        routing=load_routing_config(directory),
        applications=load_application_configs(directory),
        permissions=load_permission_policy(directory),
        file_access=load_security_config(directory).file_access,
        command_runner=load_security_config(directory).command_runner,
    )
