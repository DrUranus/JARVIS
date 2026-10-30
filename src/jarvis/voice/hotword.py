"""Local, replaceable hotword gate in front of any AudioSource. No network; it only passes audio on, it never starts an action itself."""
from __future__ import annotations

from jarvis.voice.base import AudioClip, AudioSource, HotwordDetector


class HotwordGatedSource(AudioSource):
    """record() returns None until the detector hears the hotword; the recording after that is the command.

    The clip containing the hotword is discarded. The text of the command still goes through VoiceSession -> core.handle, i.e. through the
    normal ToolRegistry/PermissionEngine confirmation; the hotword itself confirms nothing."""

    def __init__(self, source: AudioSource, detector: HotwordDetector) -> None:
        self._source, self._detector = source, detector
        self._armed = False

    def record(self) -> AudioClip | None:
        clip = self._source.record()                       # EndOfInput / VoiceUnavailableError propagate
        if not self._armed:
            if clip is not None and not clip.is_empty and self._detector.detect(clip):
                self._armed = True
            return None
        self._armed = False
        return clip
