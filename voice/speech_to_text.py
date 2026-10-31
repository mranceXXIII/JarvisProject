"""Speech-to-text engines (local processing only; spec section 7).

Faster-Whisper runs entirely on this machine - audio is never uploaded.
The engine is created lazily and reports ``available=False`` when the
dependency or model is missing, so callers can degrade honestly.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol

logger = logging.getLogger("jarvis.voice.stt")


class STTEngine(Protocol):
    """Contract for speech-to-text engines."""

    @property
    def available(self) -> bool: ...

    def transcribe(self, frames: list[Any], sample_rate: int) -> str: ...


def _import_faster_whisper() -> Any | None:
    try:
        import faster_whisper  # type: ignore

        return faster_whisper
    except Exception:
        return None


class FasterWhisperSTT:
    """Local speech-to-text using faster-whisper (lazy model load)."""

    def __init__(self, model_size: str = "base") -> None:
        self._model_size = model_size
        self._model: Any = None
        self._load_attempted = False

    @property
    def available(self) -> bool:
        if _import_faster_whisper() is None:
            return False
        if not self._load_attempted:
            # Model files download on first use; report available only
            # after a successful load attempt.
            try:
                self._ensure_model()
            except Exception as exc:
                logger.warning("whisper model '%s' failed to load: %s",
                               self._model_size, exc)
        return self._model is not None

    def _ensure_model(self) -> None:
        if self._model is None and not self._load_attempted:
            faster_whisper = _import_faster_whisper()
            if faster_whisper is None:
                self._load_attempted = True
                return
            logger.info("loading whisper model '%s' (first use may download)",
                        self._model_size)
            self._model = faster_whisper.WhisperModel(self._model_size)
            self._load_attempted = True

    def transcribe(self, frames: list[Any], sample_rate: int) -> str:
        """Transcribe captured frames to text (local inference)."""
        import numpy

        self._ensure_model()
        if self._model is None:
            raise RuntimeError("whisper model unavailable")
        if not frames:
            return ""
        audio = numpy.concatenate([f.reshape(-1) for f in frames])
        segments, _info = self._model.transcribe(
            audio, language="en", beam_size=1
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


def create_stt(model_size: str = "base") -> STTEngine:
    """Factory: returns the configured engine (may be unavailable)."""
    return FasterWhisperSTT(model_size)
