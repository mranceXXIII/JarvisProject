"""Tests for validated configuration loading (Phase 1)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.config_loader import (
    AppConfig,
    ConfigError,
    GatewayConfig,
    ProviderConfig,
    Settings,
    load_app_config,
)

PROJECT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _write_config(dir_path: Path, settings: dict | None = None, providers: list | None = None, gateways: list | None = None) -> None:
    if settings is not None:
        (dir_path / "settings.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")
    else:
        (dir_path / "settings.yaml").write_text("app:\n  name: TestJARVIS\n", encoding="utf-8")
    (dir_path / "providers.yaml").write_text(
        yaml.safe_dump({"providers": providers or []}), encoding="utf-8"
    )
    (dir_path / "gateways.yaml").write_text(
        yaml.safe_dump({"gateways": gateways or []}), encoding="utf-8"
    )


@pytest.mark.unit
class TestSettingsLoading:
    def test_load_real_project_config(self) -> None:
        config = load_app_config(PROJECT_CONFIG_DIR)
        assert isinstance(config, AppConfig)
        assert config.settings.app.name == "JARVIS"

    def test_defaults_applied_when_sections_missing(self, tmp_path: Path) -> None:
        _write_config(tmp_path)
        config = load_app_config(tmp_path)
        assert config.settings.logging.level == "INFO"
        assert config.settings.app.startup_mode == "both"

    def test_missing_file_raises_config_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="not found"):
            load_app_config(tmp_path)

    def test_invalid_yaml_raises_config_error(self, tmp_path: Path) -> None:
        (tmp_path / "settings.yaml").write_text("app: [unclosed", encoding="utf-8")
        with pytest.raises(ConfigError, match="invalid YAML"):
            load_app_config(tmp_path)

    def test_unknown_field_rejected(self, tmp_path: Path) -> None:
        _write_config(tmp_path, settings={"app": {"name": "X", "bogus_field": 1}})
        with pytest.raises(ConfigError, match="bogus_field"):
            load_app_config(tmp_path)

    def test_invalid_log_level_rejected(self, tmp_path: Path) -> None:
        _write_config(tmp_path, settings={"logging": {"level": "LOUD"}})
        with pytest.raises(ConfigError, match="level"):
            load_app_config(tmp_path)


@pytest.mark.unit
class TestProviderConfigRules:
    def test_api_key_field_is_rejected(self) -> None:
        with pytest.raises(Exception, match="api_key"):
            ProviderConfig.model_validate(
                {"name": "Bad", "type": "openai_compatible", "api_key": "sk-secret"}
            )

    def test_secret_value_inside_extra_is_rejected(self) -> None:
        with pytest.raises(Exception, match="secret-like fields"):
            ProviderConfig.model_validate(
                {"name": "Bad", "type": "custom", "extra": {"token": "abc123"}}
            )

    def test_active_provider_must_be_enabled(self) -> None:
        with pytest.raises(Exception, match="cannot be active"):
            ProviderConfig.model_validate(
                {"name": "P", "type": "ollama", "enabled": False, "active": True}
            )

    def test_valid_enabled_provider(self) -> None:
        provider = ProviderConfig.model_validate(
            {
                "name": "P",
                "type": "ollama",
                "base_url": "http://localhost:11434",
                "enabled": True,
            }
        )
        assert provider.enabled is True
        assert provider.active is False
        assert provider.timeout_seconds == 30

    def test_duplicate_provider_names_rejected(self, tmp_path: Path) -> None:
        _write_config(
            tmp_path,
            providers=[
                {"name": "Same", "type": "ollama"},
                {"name": "Same", "type": "ollama"},
            ],
        )
        config = load_app_config(tmp_path)
        from providers.provider_registry import ProviderRegistry, ProviderRegistryError

        with pytest.raises(ProviderRegistryError, match="duplicate"):
            ProviderRegistry(providers=config.providers)


@pytest.mark.unit
class TestGatewayConfig:
    def test_valid_gateway(self) -> None:
        gateway = GatewayConfig.model_validate(
            {"name": "gw", "url": "http://localhost:8080", "api_path": "/v1"}
        )
        assert gateway.url == "http://localhost:8080"
        assert gateway.enabled is False

    def test_gateway_url_required(self) -> None:
        with pytest.raises(Exception):
            GatewayConfig.model_validate({"name": "gw"})
