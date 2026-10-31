"""Voice pipeline: wake -> activate -> record -> transcribe -> command.

Orchestrates the voice components around the state machine (spec sections
3, 7). Privacy rules enforced here:
- In STANDBY only wake-word frames are processed locally.
- Muted/paused/stopped states capture NO audio at all.
- STT runs locally (faster-whisper); nothing is uploaded.

The pipeline is dependency-tolerant: any missing engine degrades the
corresponding feature honestly (no fake listening).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from core.config_loader import VoiceSettings
from core.state_manager import VoiceState, VoiceStateMachine
from security.credential_manager import CredentialManager
from voice.microphone import Microphone
from voice.speech_to_text import STTEngine, create_stt
from voice.text_to_speech import TTSEngine, create_tts
from voice.wake_word import WakeWordEngine, create_wake_engine

logger = logging.getLogger("jarvis.voice.pipeline")

CommandCallback = Callable[[str], str]


class _NoTTS:
    """Placeholder when TTS is disabled in settings."""

    @property
    def available(self) -> bool:
        return False

    def speak(self, text: str) -> None:
        return None


class VoicePipeline:
    """Runs the standby/active voice loop on a background thread."""

    def __init__(
        self,
        settings: VoiceSettings,
        state_machine: VoiceStateMachine,
        microphone: Microphone,
        stt: STTEngine,
        tts: TTSEngine,
        wake_engine: WakeWordEngine,
        on_command: CommandCallback | None = None,
        credential_manager: CredentialManager | None = None,
    ) -> None:
        self._settings = settings
        self._states = state_machine
        self._mic = microphone
        self._stt = stt
        self._tts = tts
        self._wake = wake_engine
        self._on_command = on_command
        self._credentials = credential_manager
        self._stop_event = threading.Event()
        self._cancel_capture = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_activity = time.monotonic()

    @classmethod
    def from_config(
        cls,
        settings: VoiceSettings,
        credential_manager: CredentialManager | None,
        on_command: CommandCallback | None,
    ) -> "VoicePipeline":
        access_key = None
        if credential_manager is not None:
            try:
                access_key = credential_manager.get_secret(
                    settings.wake_credential_ref
                )
            except Exception:
                access_key = None
        return cls(
            settings=settings,
            state_machine=VoiceStateMachine(),
            microphone=Microphone(settings.sample_rate, settings.input_device),
            stt=create_stt(settings.stt_model),
            tts=create_tts(settings.tts_rate) if settings.tts_enabled else _NoTTS(),
            wake_engine=create_wake_engine(access_key, settings.wake_phrase),
            on_command=on_command,
            credential_manager=credential_manager,
        )

    @property
    def state(self) -> VoiceState:
        return self._states.state

    def status_report(self) -> dict[str, Any]:
        """Honest availability report for the UI."""
        return {
            "state": self.state.value,
            "microphone": self._mic.available,
            "input_devices": self._mic.list_devices()[:5],
            "stt": self._stt.available,
            "tts": self._tts.available,
            "wake_word": self._wake.available,
            "wake_phrase": self._settings.wake_phrase,
        }

    # -- user controls (spec section 7) -----------------------------------

    def activate_manual(self) -> bool:
        """Manual activation (dashboard button/shortcut/tray).

        While MUTED or PAUSED, activation is refused: the user must unmute
        or resume explicitly (privacy-first; no accidental capture).
        """
        if self.state != VoiceState.STANDBY:
            logger.info(
                "activate ignored in state %s", self.state.value
            )
            return False
        if not self._mic.available or not self._stt.available:
            logger.warning(
                "voice activation unavailable (mic: %s, stt: %s) - stated honestly",
                self._mic.available,
                self._stt.available,
            )
            return False
        self._states.transition(VoiceState.ACTIVE)
        self._last_activity = time.monotonic()
        return True

    def mute(self) -> None:
        if self.state in (VoiceState.STANDBY, VoiceState.ACTIVE):
            self._states.transition(VoiceState.MUTED)

    def unmute(self) -> None:
        if self.state == VoiceState.MUTED:
            self._states.transition(VoiceState.STANDBY)

    def pause(self) -> None:
        if self.state in (VoiceState.STANDBY, VoiceState.MUTED):
            self._states.transition(VoiceState.PAUSED)

    def resume(self) -> None:
        if self.state == VoiceState.PAUSED:
            self._states.transition(VoiceState.STANDBY)

    def emergency_stop(self) -> None:
        """Immediately stop all voice activity (spec section 16)."""
        self._cancel_capture.set()
        self._states.transition(VoiceState.STOPPED)
        logger.warning("EMERGENCY STOP: voice subsystem halted")

    def restart(self) -> None:
        """Restart after emergency stop."""
        if self.state == VoiceState.STOPPED:
            self._cancel_capture.clear()
            self._states.transition(VoiceState.STANDBY)

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start the standby loop thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="jarvis-voice", daemon=True
        )
        self._thread.start()
        logger.info("voice pipeline started")

    def stop(self) -> None:
        """Stop the loop thread (clean shutdown)."""
        self._stop_event.set()
        self._cancel_capture.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("voice pipeline stopped")

    # -- internal loop -------------------------------------------------------

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            state = self.state
            if state == VoiceState.ACTIVE:
                self._active_tick()
            else:
                time.sleep(0.1)

    def _active_tick(self) -> None:
        """Capture one utterance, transcribe, dispatch the command."""
        try:
            frames = self._mic.record_utterance(
                max_seconds=8.0,
                should_continue=lambda: (
                    self.state == VoiceState.ACTIVE
                    and not self._cancel_capture.is_set()
                ),
            )
        except Exception as exc:
            logger.error("microphone capture failed: %s", exc)
            self._states.transition(VoiceState.STANDBY)
            return
        if self.state != VoiceState.ACTIVE:
            return
        self._states.transition(VoiceState.PROCESSING)
        try:
            text = self._stt.transcribe(frames, self._settings.sample_rate)
        except Exception as exc:
            logger.error("transcription failed: %s", exc)
            text = ""
        if not text.strip():
            logger.info("empty transcription; returning to standby")
            self._states.transition(VoiceState.STANDBY)
            return
        logger.info("voice command: %r", text)
        reply_text = ""
        try:
            if self._on_command is not None:
                reply_text = self._on_command(text) or ""
        except Exception:
            logger.exception("command handler failed")
        if self._stop_event.is_set():
            return
        if self._tts.available and reply_text:
            self._states.transition(VoiceState.SPEAKING)
            try:
                self._tts.speak(reply_text)
            except Exception as exc:
                logger.warning("speech output failed: %s", exc)
        if self.state in (VoiceState.SPEAKING, VoiceState.PROCESSING):
            self._states.transition(VoiceState.STANDBY)
