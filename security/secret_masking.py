"""Helpers for displaying and logging secrets safely.

Never print, log, or display a raw secret. Use :func:`mask_secret` for UI
display and :func:`redact_text` / :class:`SecretRedactingFilter` (core
logging) for logs.
"""

from __future__ import annotations

from core.logging_setup import MASK, SecretRedactingFilter, redact_text  # noqa: F401

VISIBLE_PREFIX_CHARS = 4
VISIBLE_SUFFIX_CHARS = 4
MIN_LENGTH_TO_MASK_PARTIALLY = 12


def mask_secret(secret: str | None) -> str:
    """Return a safe, human-recognizable representation of *secret*.

    Shows at most the first and last few characters, e.g. ``sk-1…wX9q``.
    Empty values become ``<not set>``; short values are fully masked.
    """
    if not secret:
        return "<not set>"
    if len(secret) < MIN_LENGTH_TO_MASK_PARTIALLY:
        return MASK
    prefix = secret[:VISIBLE_PREFIX_CHARS]
    suffix = secret[-VISIBLE_SUFFIX_CHARS:]
    return f"{prefix}…{suffix}"
