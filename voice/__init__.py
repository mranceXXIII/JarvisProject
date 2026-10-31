"""JARVIS voice package: wake word, microphone, STT, TTS, and pipeline.

Every engine is OPTIONAL: this package works without any voice dependency
installed, reporting each engine's availability honestly.
"""

__all__ = ["microphone", "pipeline", "speech_to_text", "text_to_speech", "wake_word"]
