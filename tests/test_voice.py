"""Tests for Phase 5: voice state machine and pipeline (fake engines)."""

from __future__ import annotations

import time

import pytest

from core.config_loader import VoiceSettings
from core.state_manager import VoiceState, VoiceStateMachine, VoiceStateError
from voice.pipeline import VoicePipeline


class FakeMic:
    """Records capture attempts; returns scripted frames."""

    available = True

    def __init__(self, frames=lambda: ["frame1", "frame2"]) -> None:
        self._frames = frames
        self.capture_calls = 0
        self.fail_next = False

    def list_devices(self):
        return ["Fake Mic"]

    def record_utterance(self, max_seconds=8.0, should_continue=lambda: True, **_):
        self.capture_calls += 1
        if self.fail_next:
            raise OSError("no device")
        time.sleep(0.05)
        return self._frames()


class FakeSTT:
    available = True

    def __init__(self, transcription=lambda frames: "open notepad"):
        self._transcription = transcription
        self.transcribed = []

    def transcribe(self, frames, sample_rate):
        self.transcribed.append(frames)
        return self._transcription(frames)


class FakeTTS:
    available = True

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def speak(self, text):
        self.spoken.append(text)


class FakeWake:
    available = True

    def process(self, frame):
        return False


def _settings(**overrides) -> VoiceSettings:
    return VoiceSettings(enabled=True, **overrides)


def _pipeline(
    frames=lambda: ["f1"], transcription=lambda f: "open notepad", on_command=None
):
    mic = FakeMic(frames)
    stt = FakeSTT(transcription)
    tts = FakeTTS()
    pipeline = VoicePipeline(
        settings=_settings(),
        state_machine=VoiceStateMachine(),
        microphone=mic,
        stt=stt,
        tts=tts,
        wake_engine=FakeWake(),
        on_command=on_command,
    )
    return pipeline, mic, stt, tts


@pytest.mark.unit
class TestVoiceStateMachine:
    def test_standby_to_active_allowed(self) -> None:
        sm = VoiceStateMachine()
        assert sm.transition(VoiceState.ACTIVE) == VoiceState.ACTIVE

    def test_illegal_transition_rejected(self) -> None:
        sm = VoiceStateMachine()
        with pytest.raises(VoiceStateError):
            sm.transition(VoiceState.PROCESSING)

    def test_stop_only_restarts_to_standby(self) -> None:
        sm = VoiceStateMachine()
        sm.transition(VoiceState.STOPPED)
        sm.transition(VoiceState.STANDBY)
        with pytest.raises(VoiceStateError):
            sm.transition(VoiceState.PROCESSING)

    def test_same_state_noop(self) -> None:
        sm = VoiceStateMachine()
        assert sm.transition(VoiceState.STANDBY) == VoiceState.STANDBY

    def test_listeners_fired_and_errors_isolated(self) -> None:
        sm = VoiceStateMachine()
        seen: list = []

        def broken(_o, _n):
            raise RuntimeError("listener bug")

        sm.on_change(lambda o, n: seen.append((o, n)))
        sm.on_change(broken)
        sm.transition(VoiceState.ACTIVE)
        assert seen == [(VoiceState.STANDBY, VoiceState.ACTIVE)]

    def test_is_operational(self) -> None:
        sm = VoiceStateMachine()
        assert sm.is_operational() is True
        sm.transition(VoiceState.MUTED)
        assert sm.is_operational() is False


@pytest.mark.unit
class TestVoicePipelineFlow:
    def test_manual_activation_runs_full_flow(self) -> None:
        commands: list[str] = []
        pipeline, mic, stt, tts = _pipeline(
            on_command=lambda text: (commands.append(text), f"Opened {text}")[1]
        )
        pipeline.start()
        try:
            assert pipeline.activate_manual() is True
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and pipeline.state.value != "standby":
                time.sleep(0.05)
            assert commands == ["open notepad"]
            assert tts.spoken == ["Opened open notepad"]
            assert mic.capture_calls == 1
            assert len(stt.transcribed) == 1
        finally:
            pipeline.stop()

    def test_empty_transcription_returns_to_standby(self) -> None:
        pipeline, _, _, tts = _pipeline(transcription=lambda f: "")
        pipeline.start()
        try:
            pipeline.activate_manual()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and pipeline.state.value != "standby":
                time.sleep(0.05)
            assert tts.spoken == []
        finally:
            pipeline.stop()

    def test_mute_blocks_activation(self) -> None:
        pipeline, mic, _, _ = _pipeline()
        pipeline.mute()
        assert pipeline.state.value == "muted"
        assert pipeline.activate_manual() is False
        assert mic.capture_calls == 0
        pipeline.unmute()
        assert pipeline.state.value == "standby"

    def test_pause_resume_flow(self) -> None:
        pipeline, _, _, _ = _pipeline()
        pipeline.pause()
        assert pipeline.state.value == "paused"
        assert pipeline.activate_manual() is False  # explicit resume required
        pipeline.resume()
        assert pipeline.state.value == "standby"
        pipeline.activate_manual()
        assert pipeline.state.value == "active"
        pipeline.stop()

    def test_emergency_stop_halts_and_requires_restart(self) -> None:
        pipeline, _, _, _ = _pipeline()
        pipeline.start()
        pipeline.activate_manual()
        pipeline.emergency_stop()
        assert pipeline.state.value == "stopped"
        assert pipeline.activate_manual() is False
        pipeline.restart()
        assert pipeline.state.value == "standby"
        pipeline.stop()

    def test_capture_failure_returns_to_standby(self) -> None:
        pipeline, mic, _, _ = _pipeline()
        mic.fail_next = True
        pipeline.start()
        pipeline.activate_manual()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and pipeline.state.value != "standby":
            time.sleep(0.05)
        assert pipeline.state.value == "standby"
        pipeline.stop()

    def test_unavailable_engines_block_activation(self) -> None:
        mic = FakeMic()
        mic.available = False
        pipeline = VoicePipeline(
            settings=_settings(),
            state_machine=VoiceStateMachine(),
            microphone=mic,
            stt=FakeSTT(),
            tts=FakeTTS(),
            wake_engine=FakeWake(),
        )
        assert pipeline.activate_manual() is False
        assert pipeline.state.value == "standby"

    def test_status_report_is_honest(self) -> None:
        mic = FakeMic()
        mic.available = False
        pipeline = VoicePipeline(
            settings=_settings(),
            state_machine=VoiceStateMachine(),
            microphone=mic,
            stt=FakeSTT(),
            tts=FakeTTS(),
            wake_engine=FakeWake(),
        )
        report = pipeline.status_report()
        assert report["microphone"] is False
        assert report["stt"] is True
        assert report["state"] == "standby"


@pytest.mark.unit
class TestVoiceEngineFactories:
    def test_stt_availability_flag(self) -> None:
        from voice.speech_to_text import create_stt

        assert isinstance(create_stt("base").available, bool)

    def test_tts_availability_flag(self) -> None:
        from voice.text_to_speech import create_tts

        assert isinstance(create_tts(180).available, bool)

    def test_wake_engine_without_key_is_manual_only(self) -> None:
        from voice.wake_word import ManualOnlyWake, create_wake_engine

        engine = create_wake_engine(None, "jarvis")
        if not engine.available:
            assert isinstance(engine, ManualOnlyWake)
        assert engine.process("frame") is False

    def test_microphone_list_devices_without_dependency(self) -> None:
        from voice.microphone import Microphone

        assert isinstance(Microphone().list_devices(), list)
