"""V2.1 Aufgabe 3: der gemeinsame Geheimnis-Detektor (jarvis.redaction) erkennt Bearer-Token. Alle Tokens sind synthetisch (zur Laufzeit zusammengesetzt, nirgends ein echtes
Geheimnis); die Tests pruefen Label und Schwaerzung, nie die Ausgabe eines Geheimnisses im Klartext."""
import logging

import pytest

from jarvis.errors import SecretRejectedError
from jarvis.memory.guarded import GuardedMemoryStore
from jarvis.memory.inmemory import InMemoryStore
from jarvis.memory.guard import SecretGuard
from jarvis.redaction import PATTERNS, REDACTED, SecretDetector

TOK = "Zx9" + "Qw4" * 6 + "p0"                    # 23 Zeichen mit Ziffern, ohne bekanntes Provider-Praefix
OPAQUE_HEX = "d41d8cd98f00b204e9800998ecf8427e"      # 32 hex
B64 = "dGVzdC10b2tlbi1mb3ItdGVzdHMtb25seQ"           # base64-artig
DET = SecretDetector()

DETECTED = [
    f"Authorization: Bearer {TOK}",
    f"authorization = bearer {TOK}",
    f"curl -H 'Authorization: Bearer {TOK}' https://example.invalid/api",
    f'headers = {{"Authorization": "Bearer {TOK}"}}',
    f"Bearer {TOK}",
    f"bearer   {TOK}",
    f"BEARER {OPAQUE_HEX}",
    f"Bearer {B64}==",
    f"Der Header lautet Bearer {TOK} und sonst nichts",
    "Authorization: Bearer abc.def.ghi",             # bestehender Fall: kurze Header-Form bleibt erkannt
    f"Authorization:Bearer {TOK}",
    f"Bearer {TOK[:8]}.{TOK[8:16]}-{TOK[16:]}~+/",
]

BENIGN = [
    "The bearer of bad news arrived",
    "Bearer tokens are described in RFC 6750",
    "Bearer authentication-scheme-description-without-digits",    # lange Prosa ohne Ziffern: kein Token
    "Bearer 2024",
    "Der Inhaber (bearer) der Karte",
    "Authorization header uses the Bearer scheme",
    "bearer-token-support is planned",
    "Die Bearer-Pruefung ist aktiv",
    "Carrier Bearer Service Version 3",
]


@pytest.mark.parametrize("text", DETECTED)
def test_bearer_tokens_are_found_and_the_description_never_contains_the_secret(text):
    found = DET.find(text)
    assert found is not None and TOK not in found and OPAQUE_HEX not in found and B64 not in found


@pytest.mark.parametrize("text", [t for t in DETECTED if "abc.def.ghi" not in t])
def test_redaction_removes_the_whole_token_not_only_the_keyword(text):
    out = DET.redact(text)
    for secret in (TOK, TOK[:8], OPAQUE_HEX, B64, TOK[8:16]):
        assert secret not in out, out
    assert REDACTED in out


def test_the_short_header_form_is_redacted_completely_too():
    assert "abc.def.ghi" not in DET.redact("Authorization: Bearer abc.def.ghi")


def test_the_surrounding_text_stays_readable():
    out = DET.redact(f"Anfrage fehlgeschlagen: Authorization: Bearer {TOK} wurde abgelehnt (401)")
    assert out.startswith("Anfrage fehlgeschlagen:") and out.endswith("wurde abgelehnt (401)")


@pytest.mark.parametrize("text", BENIGN)
def test_prose_and_non_tokens_are_no_false_positives(text):
    assert DET.find(text) is None and DET.redact(text) == text


def test_existing_rules_are_all_still_there_and_unchanged_in_order():
    names = [n for n, _ in PATTERNS]
    for needed in ("API key", "GitHub token", "AWS access key", "Slack token", "Google API key", "JWT", "private key", "credentials in URL", "credential statement",
                   "long random token"):
        assert needed in names
    assert [n for n in names if n != "Bearer token"] == ["API key", "GitHub token", "AWS access key", "Slack token", "Google API key", "JWT", "private key",
                                                         "credentials in URL", "credential statement", "long random token"]


@pytest.mark.parametrize("text", ["sk-" + "a1" * 12, "ghp_" + "A1" * 15, "password=hunter2hunter2", "token: abcdefgh", "postgres://admin:s3cret@db.example.com/prod"])
def test_previously_detected_secrets_are_still_detected(text):
    assert DET.find(text) is not None


def test_memory_refuses_to_store_a_bearer_token_and_stores_prose():
    mem = GuardedMemoryStore(InMemoryStore(), SecretGuard())
    with pytest.raises(SecretRejectedError) as exc:
        mem.add(f"Merke dir: Authorization: Bearer {TOK}")
    assert TOK not in str(exc.value) and mem.count() == 0
    assert mem.add("Wir nutzen Bearer-Authentifizierung fuer die interne API").content


def test_the_detector_logs_nothing_and_never_returns_the_secret(caplog):
    with caplog.at_level(logging.DEBUG):
        DET.find(f"Bearer {TOK}")
        DET.redact(f"Bearer {TOK}")
    assert TOK not in caplog.text


def test_redact_mapping_hides_bearer_values_in_free_text_fields():
    out = DET.redact_mapping({"note": f"sent Bearer {TOK}", "ok": "fine"})
    assert TOK not in out["note"] and out["ok"] == "fine"


def test_no_catastrophic_backtracking_on_long_input():
    import time
    t0 = time.monotonic()
    DET.find("Bearer " + "a" * 200_000 + "!")
    DET.redact("bearer " + "1" * 200_000)
    DET.find("Authorization: " + " " * 50_000 + "x")
    assert time.monotonic() - t0 < 5.0
