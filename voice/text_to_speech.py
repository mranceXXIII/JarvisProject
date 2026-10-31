"""Text-to-speech engines (spec section 7).

Primary engine: Windows SAPI speech via ``pyttsx3`` (optional dependency).
Reports ``available=False`` when the dependency or voice backend is
missing so callers degrade honestly to text-only.
"""

from __future__ import annotations

import logging
import threading
from typing import Protocol

logger = logging.getLogger("jarvis.voice.tts")


class TTSEngine(Protocol):
    """Contract for text-to-speech engines."""

    @property
    def available(self) -> bool: ...

    def speak(self, text: str) -> None: ...


class Pyttsx3TTS:
    """Windows SAPI speech via pyttsx3; each utterance gets a fresh engine
    instance because pyttsx3 run loops are not reusable across threads."""

    def __init__(self, rate: int = 180) -> None:
        self._rate = rate
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        try:
            import pyttsx3  # type: ignore

            return True
        except Exception:
            return False

    def speak(self, text: str) -> None:
        """Speak *text* synchronously on the calling thread."""
        if not text.strip():
            return
        with self._lock:
            try:
                import pyttsx3  # type: ignore

                engine = pyttsx3.init()
                engine.setProperty("rate", self._rate)
                engine.say(text)
                engine.runAndWait()
                engine.stop()
            except Exception as exc:
                logger.warning("TTS failed: %s", exc)


def create_tts(rate: int = 180) -> TTSEngine:
    return Pyttsx3TTS(rate)
