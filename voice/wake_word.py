"""Wake-word engines (local standby detection; spec section 7).

Primary engine: Picovoice Porcupine (local, keyword-specific, requires an
access key from the secure credential store and agreement with Picovoice's
terms). Availability is probed lazily; when unavailable, JARVIS remains
usable via manual/text activation - stated honestly, never faked.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol

logger = logging.getLogger("jarvis.voice.wake")


class WakeWordEngine(Protocol):
    """Contract for standby wake-word detection."""

    @property
    def available(self) -> bool: ...

    def process(self, frame: Any) -> bool:
        """Return True when the wake phrase was detected in *frame*."""
        ...


def _import_porcupine() -> Any | None:
    try:
        import pvporcupine  # type: ignore

        return pvporcupine
    except Exception:
        return None


class PorcupineWakeWord:
    """Porcupine detection for a built-in or custom keyword."""

    def __init__(self, access_key: str | None, keyword: str = "jarvis") -> None:
        self._access_key = access_key
        self._keyword = keyword
        self._porcupine: Any = None
        self._init_attempted = False

    @property
    def available(self) -> bool:
        self._ensure_engine()
        return self._porcupine is not None

    def frame_length(self) -> int:
        """Required PCM frame length for process()."""
        self._ensure_engine()
        if self._porcupine is None:
            return 512
        return self._porcupine.frame_length

    def _ensure_engine(self) -> None:
        if self._init_attempted:
            return
        self._init_attempted = True
        porcupine_module = _import_porcupine()
        if porcupine_module is None:
            logger.info("pvporcupine not installed; wake word unavailable")
            return
        if not self._access_key:
            logger.info(
                "no Picovoice access key in credential store '%s'; "
                "wake word unavailable",
                "jarvis/picovoice-access-key",
            )
            return
        try:
            self._porcupine = porcupine_module.create(
                access_key=self._access_key, keyword=self._keyword
            )
            logger.info("wake word engine ready (keyword: %s)", self._keyword)
        except Exception as exc:
            # Invalid key, quota exceeded, unsupported keyword, ...
            logger.warning("porcupine init failed: %s", type(exc).__name__)

    def process(self, frame: Any) -> bool:
        self._ensure_engine()
        if self._porcupine is None:
            return False
        return self._porcupine.process(frame) == 1


class ManualOnlyWake:
    """Always-off wake engine: JARVIS must be activated manually."""

    @property
    def available(self) -> bool:
        return False

    def process(self, frame: Any) -> bool:
        return False


def create_wake_engine(
    access_key: str | None, keyword: str = "jarvis"
) -> WakeWordEngine:
    """Factory: Porcupine when usable, otherwise manual-only activation."""
    engine = PorcupineWakeWord(access_key, keyword)
    if engine.available:
        return engine
    logger.info(
        "wake word unavailable - use dashboard/button activation (stated "
        "honestly, not faked)"
    )
    return ManualOnlyWake()
