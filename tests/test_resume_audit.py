"""F-S9-1: die Rueckfrage `resume_step` und ihre Antwort stehen im Audit (confirmation_requested / _accepted / _rejected). Nur Audit, keine Aenderung der
Entscheidung: allow_once = ja, alles andere = nein, Fehler = nein. Kein Netz, keine Schluessel oder Zieltexte im Eintrag."""
from types import SimpleNamespace

import pytest

from jarvis.interface.cli import resume_confirm_with_audit
from jarvis.permissions import ConfirmationChoice


class Audit:
    def __init__(self, fail=False):
        self.events, self.fail = [], fail

    def record(self, event):
        if self.fail:
            raise RuntimeError("audit down")
        self.events.append(event)
        return True


def run(choice, audit, secret="sk-GEHEIM-1234567890"):
    provider = SimpleNamespace(confirm=lambda req: choice if not isinstance(choice, Exception) else (_ for _ in ()).throw(choice))
    core = SimpleNamespace(permissions=SimpleNamespace(audit=audit, confirmation=provider))
    return resume_confirm_with_audit(core, 1, f"Schritt mit {secret}")


def types(a):
    return [(e.type.value, e.tool, e.action, e.resource) for e in a.events]


def test_allow_once_audits_requested_and_accepted_and_returns_true():
    a = Audit()
    assert run(ConfirmationChoice.ALLOW_ONCE, a) is True
    assert types(a) == [("confirmation_requested", "jarvis", "resume_step", "journal"), ("confirmation_accepted", "jarvis", "resume_step", "journal")]


@pytest.mark.parametrize("choice", [ConfirmationChoice.DENY, ConfirmationChoice.ALLOW_SESSION, RuntimeError("x")])
def test_everything_else_is_a_no_and_audits_rejected(choice):
    a = Audit()
    assert run(choice, a) is False
    assert [t[0] for t in types(a)] == ["confirmation_requested", "confirmation_rejected"]


def test_audit_failure_means_no_and_nothing_is_asked():
    assert run(ConfirmationChoice.ALLOW_ONCE, Audit(fail=True)) is False


def test_audit_entries_carry_no_step_text_or_secret():
    a = Audit()
    run(ConfirmationChoice.DENY, a, secret="sk-GEHEIM-1234567890")
    assert "GEHEIM" not in repr([vars(e) if hasattr(e, "__dict__") else e for e in a.events])
