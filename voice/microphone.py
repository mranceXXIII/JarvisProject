"""Microphone control with privacy-first behaviour (spec section 7).

Uses ``sounddevice`` when installed; otherwise reports unavailable. When
muted or paused, NO audio is captured at all - frames are never read from
the device, so nothing can leak even to local processing.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

logger = logging.getLogger("jarvis.voice.microphone")

try:  # optional dependency
    import sounddevice  # type: ignore

    _sounddevice: Any = sounddevice
except Exception:  # pragma: no cover - depends on environment
    _sounddevice = None


def sounddevice_available() -> bool:
    return _sounddevice is not None


class Microphone:
    """Captures audio frames locally; nothing is transmitted."""

    def __init__(self, sample_rate: int = 16000, device: str | None = None) -> None:
        self._sample_rate = sample_rate
        self._device = device

    @property
    def available(self) -> bool:
        return _sounddevice is not None

    def list_devices(self) -> list[str]:
        """Names of available input devices (empty when unavailable)."""
        if _sounddevice is None:
            return []
        try:
            devices = _sounddevice.query_devices()
        except Exception as exc:
            logger.warning("could not query audio devices: %s", exc)
            return []
        return [d["name"] for d in devices if d.get("max_input_channels", 0) > 0]

    def record_utterance(
        self,
        max_seconds: float = 8.0,
        silence_threshold: float = 0.01,
        silence_seconds: float = 1.2,
        should_continue: Callable[[], bool] = lambda: True,
    ) -> list[Any]:
        """Record until silence or max_seconds; returns float frames.

        Frames stay in memory on this machine only.
        """
        if _sounddevice is None:
            raise RuntimeError(
                "sounddevice is not installed; microphone unavailable"
            )
        import numpy  # sounddevice requires numpy; both optional

        frames: list[Any] = []
        silent_frames = 0
        frame_length = int(self._sample_rate * 0.1)
        stream = _sounddevice.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            device=self._device,
        )
        with stream:
            deadline = time.monotonic() + max_seconds
            while (
                time.monotonic() < deadline
                and should_continue()
                and silent_frames * 0.1 < silence_seconds
            ):
                data, overflowed = stream.read(frame_length)
                if overflowed:
                    logger.warning("audio buffer overflowed; frame dropped")
                frames.append(data.copy())
                if float(numpy.abs(data).mean()) < silence_threshold:
                    silent_frames += 1
                else:
                    silent_frames = 0
        return frames
