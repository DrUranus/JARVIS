"""Voice interface: an additional front-end for JarvisCore (the core stays text-only)."""
from jarvis.voice.base import AudioClip, AudioPlayer, AudioSource, HotwordDetector, Listener, Speaker, STTProvider, TTSProvider
from jarvis.voice.factory import (build_listener, build_speaker, register_audio_player, register_audio_source,
                                  register_hotword_detector, register_stt, register_tts)
from jarvis.voice.session import VoiceSession

__all__ = ["AudioClip", "AudioPlayer", "AudioSource", "Listener", "Speaker", "STTProvider", "TTSProvider",
           "VoiceSession", "build_listener", "build_speaker", "register_stt", "register_tts",
           "register_audio_source", "register_audio_player", "HotwordDetector", "register_hotword_detector"]
