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

from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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


class Settings(BaseModel):
    """Contents of ``settings.yaml``."""

    model_config = ConfigDict(extra="forbid")

    app: AppSettings = Field(default_factory=AppSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


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
    )
