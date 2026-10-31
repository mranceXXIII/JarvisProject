"""Voice state machine (spec sections 3, 7, 17).

States:
  STANDBY     : only lightweight wake-word detection runs
  ACTIVE      : microphone capturing, ready for a command
  PROCESSING  : a command is being transcribed/executed
  SPEAKING    : JARVIS is speaking a reply
  MUTED       : microphone fully off (no capture at all - privacy)
  PAUSED      : voice subsystem suspended (no wake, no capture)
  STOPPED     : emergency stop; requires explicit restart

Transitions are validated; illegal transitions raise VoiceStateError.
Thread-safety: a lock guards state changes since the pipeline runs on
background threads while the UI reads state.
"""

from __future__ import annotations

import logging
import threading
from enum import Enum

logger = logging.getLogger("jarvis.core.state")


class VoiceState(Enum):
    STANDBY = "standby"
    ACTIVE = "active"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    MUTED = "muted"
    PAUSED = "paused"
    STOPPED = "stopped"


class VoiceStateError(RuntimeError):
    """Raised on an illegal state transition."""


_TRANSITIONS: dict[VoiceState, frozenset[VoiceState]] = {
    VoiceState.STANDBY: frozenset(
        {VoiceState.ACTIVE, VoiceState.MUTED, VoiceState.PAUSED, VoiceState.STOPPED}
    ),
    VoiceState.ACTIVE: frozenset(
        {
            VoiceState.PROCESSING,
            VoiceState.STANDBY,
            VoiceState.MUTED,
            VoiceState.PAUSED,
            VoiceState.STOPPED,
        }
    ),
    VoiceState.PROCESSING: frozenset(
        {VoiceState.SPEAKING, VoiceState.ACTIVE, VoiceState.STANDBY, VoiceState.STOPPED}
    ),
    VoiceState.SPEAKING: frozenset(
        {VoiceState.STANDBY, VoiceState.ACTIVE, VoiceState.STOPPED}
    ),
    VoiceState.MUTED: frozenset(
        {VoiceState.STANDBY, VoiceState.PAUSED, VoiceState.STOPPED}
    ),
    VoiceState.PAUSED: frozenset(
        {VoiceState.STANDBY, VoiceState.MUTED, VoiceState.STOPPED}
    ),
    VoiceState.STOPPED: frozenset({VoiceState.STANDBY}),  # only explicit restart
}


class VoiceStateMachine:
    """Validated, thread-safe voice state transitions."""

    def __init__(self, initial: VoiceState = VoiceState.STANDBY) -> None:
        self._state = initial
        self._lock = threading.Lock()
        self._listeners: list = []

    @property
    def state(self) -> VoiceState:
        with self._lock:
            return self._state

    def on_change(self, listener) -> None:
        """Register a callback fired with (old_state, new_state)."""
        with self._lock:
            self._listeners.append(listener)

    def transition(self, new_state: VoiceState) -> VoiceState:
        with self._lock:
            old = self._state
            if new_state == old:
                return old
            if new_state not in _TRANSITIONS[old]:
                raise VoiceStateError(
                    f"illegal transition {old.value} -> {new_state.value}"
                )
            self._state = new_state
        logger.info("voice state: %s -> %s", old.value, new_state.value)
        for listener in tuple(self._listeners):
            try:
                listener(old, new_state)
            except Exception:  # listeners must not break the pipeline
                logger.exception("voice state listener failed")
        return new_state

    def is_operational(self) -> bool:
        """True when voice can legally capture or listen right now."""
        return self.state in (
            VoiceState.STANDBY,
            VoiceState.ACTIVE,
            VoiceState.PROCESSING,
            VoiceState.SPEAKING,
        )
