"""Provider registries (same pattern as llm.factory). Config selects engines by name."""
from __future__ import annotations

from typing import Callable, Generic, TypeVar

from jarvis.config import VoiceSettings
from jarvis.errors import STTError, VoiceError
from jarvis.voice.base import (AudioPlayer, AudioSource, HotwordDetector, Listener, Speaker, STTProvider, TTSProvider)
from jarvis.voice.hotword import HotwordGatedSource
from jarvis.voice.composed import SpeechListener, TTSSpeaker
from jarvis.voice.console import ConsoleListener, ConsoleSpeaker
from jarvis.voice.devices import NullPlayer, SoundDeviceSource, SystemPlayer
from jarvis.voice.mock import MockAudioPlayer, MockAudioSource, MockHotwordDetector, MockSTT, MockTTS
from jarvis.voice.local_stt import LocalWhisperSTT
from jarvis.voice.stt_strategy import FallbackSTT
from jarvis.voice.openai_provider import OpenAISTT, OpenAITTS
from jarvis.voice.system_tts import SystemTTS
from jarvis.voice.windows_tts import WindowsTTS
from jarvis.voice.vad import EnergyDetector, SpeechDetector, load_silero_detector

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._factories: dict[str, Callable[[VoiceSettings], T]] = {}

    def register(self, name: str, factory: Callable[[VoiceSettings], T]) -> None:
        self._factories[name.lower()] = factory

    def names(self) -> list[str]:
        return sorted(self._factories)

    def create(self, name: str, settings: VoiceSettings) -> T:
        try:
            factory = self._factories[name.lower()]
        except KeyError:
            raise VoiceError(f"unknown {self.kind} {name!r}; available: {self.names()}") from None
        return factory(settings)


STT_PROVIDERS: Registry[STTProvider] = Registry("STT provider")
TTS_PROVIDERS: Registry[TTSProvider] = Registry("TTS provider")
AUDIO_SOURCES: Registry[AudioSource] = Registry("audio input")
AUDIO_PLAYERS: Registry[AudioPlayer] = Registry("audio output")
HOTWORD_DETECTORS: Registry[HotwordDetector] = Registry("hotword detector")
VAD_DETECTORS: Registry[SpeechDetector] = Registry("VAD detector")

register_stt = STT_PROVIDERS.register
register_tts = TTS_PROVIDERS.register
register_audio_source = AUDIO_SOURCES.register
register_audio_player = AUDIO_PLAYERS.register
register_hotword_detector = HOTWORD_DETECTORS.register
register_vad_detector = VAD_DETECTORS.register

register_stt("mock", lambda s: MockSTT())


def stt_hints(s: VoiceSettings) -> str | None:
    """Kontext-/Stichworthinweis fuer die Erkennung (nur Schreibweisen von Eigennamen/Fachwoertern, keine Befehle)."""
    parts = [s.stt_prompt.strip()] if s.stt_prompt and s.stt_prompt.strip() else []
    if s.stt_keywords:
        parts.append("Begriffe: " + ", ".join(s.stt_keywords) + ".")
    return " ".join(parts) or None


def _openai_stt(s: VoiceSettings) -> OpenAISTT:
    return OpenAISTT(s.api_key, s.stt_model, s.base_url, s.timeout, keywords=s.stt_keywords, prompt=s.stt_prompt)


def _local_stt(s: VoiceSettings, model_dir: str | None) -> LocalWhisperSTT:
    return LocalWhisperSTT(model_dir, device=s.stt_device, compute_type=s.stt_compute_type, timeout=s.timeout, hints=stt_hints(s))


def build_stt_chain(s: VoiceSettings, *, cloud: bool) -> STTProvider:
    """Lokales Hauptmodell, dann lokales Rueckfallmodell; Cloud NUR mit cloud=True UND voice.stt_cloud_enabled UND Schluessel. Ein einzelner Provider bleibt unverpackt."""
    providers: list[STTProvider] = []
    labels: list[str] = []
    problems: list[str] = []
    seen: set[str] = set()
    for label, model_dir in (("local", s.stt_model_dir), ("local-fallback", s.stt_fallback_model_dir)):
        if label == "local-fallback" and not model_dir:
            continue
        key = str(model_dir).casefold()
        if key in seen:
            continue
        seen.add(key)
        try:
            providers.append(_local_stt(s, model_dir))
            labels.append(label)
        except STTError as exc:
            problems.append(f"{label}: {exc}")
    if cloud and s.stt_cloud_enabled and s.api_key:
        providers.append(_openai_stt(s))
        labels.append("openai")
    elif cloud and s.stt_cloud_enabled:
        problems.append("openai: voice.stt_cloud_enabled ist an, aber kein Schluessel gesetzt (OPENAI_API_KEY)")
    if not providers:
        raise STTError("Spracherkennung nicht verfuegbar. " + (" | ".join(problems) or "voice.stt_model_dir setzen (lokales Modell) oder die Cloud ausdruecklich aktivieren."))
    for note in problems:
        import logging
        logging.getLogger("jarvis.voice").warning("STT provider skipped: %s", note)
    return providers[0] if len(providers) == 1 else FallbackSTT(providers, labels=labels)


register_stt("openai", _openai_stt)
register_stt("local", lambda s: build_stt_chain(s, cloud=False))
register_stt("auto", lambda s: build_stt_chain(s, cloud=True))
register_tts("mock", lambda s: MockTTS())
register_tts("system", lambda s: SystemTTS(s.tts_command))
register_tts("windows", lambda s: WindowsTTS())
register_tts("openai", lambda s: OpenAITTS(s.api_key, AUDIO_PLAYERS.create(s.audio_output, s), s.tts_model,
                                           s.tts_voice, s.base_url, s.timeout))
register_audio_source("mock", lambda s: MockAudioSource())
register_vad_detector("energy", lambda s: EnergyDetector(s.silence_threshold))
register_vad_detector("silero", lambda s: load_silero_detector())   # faster-whisper erst hier importiert (lazy)
register_audio_source("sounddevice", lambda s: SoundDeviceSource(
    s.sample_rate, s.silence_threshold, s.silence_seconds, s.max_record_seconds,
    detector=None if s.vad_provider.lower() == "none" else VAD_DETECTORS.create(s.vad_provider, s),
    min_speech_seconds=s.vad_min_speech_seconds, device=s.audio_device))
register_audio_player("mock", lambda s: MockAudioPlayer())
register_audio_player("null", lambda s: NullPlayer())
register_audio_player("system", lambda s: SystemPlayer())
register_hotword_detector("mock", lambda s: MockHotwordDetector())


def build_listener(settings: VoiceSettings, input_fn: Callable[[str], str] = input,
                   guard: Callable[[], str | None] | None = None) -> Listener:
    """`guard` (Notaus/Sitzungsbudget, von bootstrap.py geliefert) bricht eine laufende Aufnahme mit VoiceUnavailableError ab."""
    if settings.stt_provider.lower() == "console":
        return ConsoleListener(input_fn)
    stt = STT_PROVIDERS.create(settings.stt_provider, settings)
    if isinstance(stt, FallbackSTT) and guard is not None:
        stt.guard = guard                                # Not-Aus/Budget gilt vor jedem Provider der Kette (nie auf die Cloud ausweichen)
    source = AUDIO_SOURCES.create(settings.audio_input, settings)
    if guard is not None:
        source.guard = guard
    if settings.hotword_detector.lower() != "none":
        source = HotwordGatedSource(source, HOTWORD_DETECTORS.create(settings.hotword_detector, settings))
    return SpeechListener(source, stt, settings.language)


def build_speaker(settings: VoiceSettings, output_fn: Callable[[str], None] = print, guard: Callable[[], str | None] | None = None) -> Speaker:
    """`guard` (Not-Aus, von bootstrap.py geliefert) verhindert bei Providern, die es unterstuetzen (z. B. `windows`), dass eine NEUE Sprachausgabe startet."""
    if settings.tts_provider.lower() == "console":
        return ConsoleSpeaker(output_fn)
    tts = TTS_PROVIDERS.create(settings.tts_provider, settings)
    if guard is not None:
        tts.guard = guard
    return TTSSpeaker(tts)
