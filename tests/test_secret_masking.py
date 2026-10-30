"""Tests for secret masking and log redaction (Phase 1 acceptance criterion 6)."""

from __future__ import annotations

import logging

import pytest

from core.logging_setup import (
    MASK,
    SecretRedactingFilter,
    SecretRegistry,
    redact_text,
)
from security.secret_masking import mask_secret


@pytest.mark.unit
class TestMaskSecret:
    def test_long_secret_shows_prefix_and_suffix(self) -> None:
        assert mask_secret("sk-abcdef1234567890wxyz") == "sk-a…wxyz"

    def test_short_secret_fully_masked(self) -> None:
        assert mask_secret("short") == MASK

    def test_empty_secret_placeholder(self) -> None:
        assert mask_secret("") == "<not set>"
        assert mask_secret(None) == "<not set>"

    def test_masked_output_never_contains_middle(self) -> None:
        secret = "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
        masked = mask_secret(secret)
        assert "EFGHIJKLMNOP" not in masked


@pytest.mark.unit
class TestRedactText:
    def test_registered_secret_is_masked(self) -> None:
        registry = SecretRegistry()
        secret = "super-secret-api-key-value-42"
        registry.register(secret)
        text = redact_text(f"failed with key {secret}", registry.snapshot())
        assert secret not in text
        assert MASK in text

    def test_known_token_patterns_are_masked(self) -> None:
        text = "error near sk-abcdefghijklmnopqrstuvwxyz123456"
        redacted = redact_text(text, ())
        assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in redacted
        assert MASK in redacted

    def test_short_values_not_registered(self) -> None:
        registry = SecretRegistry()
        registry.register("tiny")
        assert registry.snapshot() == ()

    def test_clear_empties_registry(self) -> None:
        registry = SecretRegistry()
        registry.register("a-very-long-secret-value")
        registry.clear()
        assert registry.snapshot() == ()


@pytest.mark.unit
class TestLogRedaction:
    def test_log_record_message_is_redacted(self) -> None:
        secret = "my-private-credential-value-1234"
        log_filter = SecretRedactingFilter(secrets=(secret,))
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="connecting using %s",
            args=(secret,),
            exc_info=None,
        )
        assert log_filter.filter(record) is True
        assert secret not in record.getMessage()
        assert MASK in record.getMessage()

    def test_token_pattern_redacted_in_record(self) -> None:
        log_filter = SecretRedactingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="header: Bearer abcdefghijklmnopqrstuvwxyz123456",
            args=(),
            exc_info=None,
        )
        log_filter.filter(record)
        assert "abcdefghijklmnopqrstuvwxyz123456" not in record.getMessage()
