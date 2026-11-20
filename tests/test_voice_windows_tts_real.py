"""WP05b, nur Windows: der echte Provider mit echter Windows PowerShell 5.1 + System.Speech, Ausgabe in WAV-Dateien (kein Audiogeraet noetig).

Die Tests werden unter Linux gar nicht erst definiert (kein Skip, damit die Skip-Zahlen der Linux-Laeufe unveraendert bleiben); der Windows-CI-Lauf ist der Nachweis. Ist auf dem Runner
KEINE Stimme installiert, werden die Synthese-Tests mit klarer Begruendung uebersprungen - das gilt NICHT als bestanden (Skip-Bericht) und die Hoerprobe am PC bleibt Pflicht (Owner-Abnahme,
docs/WINDOWS_V2_ABNAHME.md Abschnitt 6). Das Protokoll (print) nennt PowerShell-Version und Stimmennamen, nie Inhalte."""
from __future__ import annotations

import subprocess
import sys
import threading
import time
import wave

import pytest

from jarvis.errors import TTSError, VoiceUnavailableError

if sys.platform == "win32":
    from jarvis.voice.windows_tts import WindowsTTS

    DIAG = ("$PSVersionTable.PSVersion.ToString();Add-Type -AssemblyName System.Speech;"
            "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices()|ForEach-Object{$_.VoiceInfo.Name+'|'+$_.VoiceInfo.Culture}")

    @pytest.fixture(scope="module")
    def diagnosis():
        done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", DIAG], capture_output=True, text=True, timeout=120, shell=False)
        lines = [x.strip() for x in done.stdout.splitlines() if x.strip()]
        print("\nWindows PowerShell:", lines[0] if lines else "?", "| Stimmen:", lines[1:] or "keine")
        assert done.returncode == 0, "Windows PowerShell mit System.Speech ist auf diesem Rechner nicht nutzbar"
        return lines

    def speak_to_wav(tmp_path, name, text, **kw):
        out = tmp_path / name
        try:
            WindowsTTS(wave_file=str(out), **kw).speak(text)
        except VoiceUnavailableError as exc:
            pytest.skip(f"keine Windows-Stimme auf diesem Rechner ({exc}); kein Nachweis der Synthese - Hoerprobe am PC bleibt Pflicht")
        return out

    def seconds(path):
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / w.getframerate()

    def test_powershell_and_system_speech_are_present(diagnosis):
        assert diagnosis[0].startswith("5.")                                           # Windows PowerShell 5.1 (Bordmittel)

    def test_the_provider_writes_a_valid_wav_and_longer_text_gives_longer_audio(diagnosis, tmp_path):
        short = speak_to_wav(tmp_path, "kurz.wav", "Hallo.")
        long_ = speak_to_wav(tmp_path, "lang.wav", "Dies ist ein längerer Satz, der deutlich mehr Zeit zum Sprechen braucht als ein kurzes Hallo.")
        assert short.stat().st_size > 44 and short.read_bytes()[:4] == b"RIFF" and short.read_bytes()[8:12] == b"WAVE"
        assert seconds(long_) > seconds(short) > 0                                      # der Text kam über stdin an (sonst gleich lang)

    def test_umlauts_arrive_through_stdin(diagnosis, tmp_path):
        plain = speak_to_wav(tmp_path, "a.wav", "Hi.")
        umlaut = speak_to_wav(tmp_path, "b.wav", "Größe, Übung, Straße und Äpfel über Öl.")
        assert seconds(umlaut) > seconds(plain) > 0

    def test_an_injection_text_is_only_spoken_never_executed(diagnosis, tmp_path):
        marker = tmp_path / "pwned.txt"
        text = f'"; Set-Content -Path \'{marker}\' -Value x; "  $(Set-Content -Path \'{marker}\' -Value y)  `n -Command Set-Content -Path \'{marker}\' -Value z'
        out = speak_to_wav(tmp_path, "inj.wav", text)
        assert out.stat().st_size > 44 and not marker.exists()

    def test_the_timeout_ends_the_real_process_and_raises_a_tts_error(diagnosis, tmp_path):
        tts = WindowsTTS(wave_file=str(tmp_path / "t.wav"), timeout=0.01)
        with pytest.raises(TTSError) as e:
            tts.speak("Dieser Text braucht länger als ein hundertstel Sekunde. " * 5)
        assert "Zeit" in str(e.value) and not tts.speaking

    def test_stop_ends_a_real_running_speech_and_it_is_not_an_error(diagnosis, tmp_path):
        tts = WindowsTTS(wave_file=str(tmp_path / "s.wav"), timeout=120)
        box = {}

        def run():
            try:
                tts.speak("Ein langer Text, der abgebrochen wird. " * 40)
            except BaseException as exc:                                               # noqa: BLE001
                box["error"] = exc

        t = threading.Thread(target=run, daemon=True)
        t.start()
        end = time.monotonic() + 30
        while not tts.speaking and time.monotonic() < end and t.is_alive():
            time.sleep(0.02)
        tts.stop()
        t.join(30)
        assert not t.is_alive() and not tts.speaking and not isinstance(box.get("error"), (OSError, AttributeError))
