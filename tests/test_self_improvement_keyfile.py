"""The HMAC key file: creation, permissions, ACLs.

Three kinds of tests, kept apart on purpose:
* PLATFORM-NEUTRAL (run everywhere): the ACL decision on fixture SDDL strings, the order and failure handling of key creation against a FAKE acl helper, and real
  multi-process creation. They prove the logic; they say nothing about what Windows really does.
* POSIX: the mode bits.
* WINDOWS ONLY (skipped elsewhere with a stated reason): the real PowerShell / icacls calls on real files. These are the only tests that can show that the Windows
  mechanism works. They read ACLs independently of the production parser (PowerShell, SID output) and only change ACLs of files/folders inside pytest's tmp_path.
Unauthorized access by ANOTHER user can not be reproduced without a second account; the Windows tests therefore assert the ACL itself (who is granted access) and that an
over-broad ACL is refused."""
from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from jarvis.self_improvement import IntegrityError
from jarvis.self_improvement import store as store_mod
from jarvis.self_improvement.store import load_key
from jarvis.self_improvement.winsec import ADMINISTRATORS_SID, SYSTEM_SID, WindowsAcl, acl_problems, parse_sddl

WIN = sys.platform.startswith("win")
USER = "S-1-5-21-1111111111-2222222222-3333333333-1001"
OTHER = "S-1-5-21-1111111111-2222222222-3333333333-1002"
SRC = str(Path(store_mod.__file__).resolve().parents[2])


# ---- PLATFORM-NEUTRAL: the decision on the effective ACL --------------------------------------------------------------------------------------------
ACCEPT = {
    "protected-user-system-admins": f"O:{USER}G:SYD:PAI(A;;FA;;;{USER})(A;;FA;;;SY)(A;;FA;;;BA)",
    "owner-is-administrators-elevated-process": f"O:BAG:BAD:PAR(A;;FA;;;BA)(A;;FA;;;SY)(A;;FA;;;{USER})",
    "only-user": f"O:{USER}G:SYD:P(A;;FA;;;{USER})",
    "deny-ace-for-everyone-is-not-a-grant": f"O:{USER}G:SYD:PAI(D;;FA;;;WD)(A;;FA;;;{USER})",
    "inherit-only-entry-does-not-apply-to-the-file": f"O:{USER}G:SYD:PAI(A;IOCI;FA;;;BU)(A;;FA;;;{USER})",
    "owner-rights-with-acceptable-owner": f"O:{USER}G:SYD:PAI(A;;FA;;;OW)(A;;FA;;;{USER})",
}
REFUSE = {
    "inherited-everyone": (f"O:{USER}G:SYD:(A;ID;FA;;;WD)(A;ID;FA;;;SY)(A;ID;FA;;;{USER})", "Everyone"),
    "inherited-users-read": (f"O:{USER}G:DUD:AI(A;ID;0x1200a9;;;BU)(A;ID;FA;;;{USER})", "Users"),
    "authenticated-users": (f"O:{USER}G:SYD:PAI(A;;FA;;;{USER})(A;;FR;;;AU)", "Authenticated Users"),
    "interactive": (f"O:{USER}G:SYD:PAI(A;;FA;;;{USER})(A;;FR;;;IU)", "Interactive"),
    "another-user": (f"O:{USER}G:SYD:PAI(A;;FA;;;{USER})(A;;FA;;;{OTHER})", OTHER),
    "another-user-owns-the-file": (f"O:{OTHER}G:SYD:PAI(A;;FA;;;{USER})", "owner"),
    "null-dacl": (f"O:{USER}G:SYD:NO_ACCESS_CONTROL", "NULL DACL"),
    "domain-relative-alias-is-unknown-and-refused": (f"O:{USER}G:SYD:PAI(A;;FA;;;DU)(A;;FA;;;{USER})", "DU"),
    "conditional-allow-ace": (f"O:{USER}G:SYD:PAI(XA;;FA;;;WD;(@User.Title==\"x\"))(A;;FA;;;{USER})", "Everyone"),
    "nobody-has-access": (f"O:{USER}G:SYD:P", "no ACE grants"),
    "not-sddl": ("hello", "could not be parsed"),
    "unbalanced": (f"O:{USER}G:SYD:PAI(A;;FA;;;{USER}", "could not be parsed"),
    "empty": ("", "could not be parsed"),
}


@pytest.mark.parametrize("sddl", list(ACCEPT.values()), ids=list(ACCEPT))
def test_acceptable_acls_are_accepted(sddl):
    assert acl_problems(sddl, USER) == []


@pytest.mark.parametrize("sddl, needle", list(REFUSE.values()), ids=list(REFUSE))
def test_every_other_acl_is_refused_and_says_why(sddl, needle):
    problems = acl_problems(sddl, USER)
    assert problems and any(needle in p for p in problems), problems


def test_unknown_current_user_is_a_problem_not_a_pass():
    assert acl_problems(ACCEPT["only-user"], "") and acl_problems(ACCEPT["only-user"], "not-a-sid")


def test_parse_sddl_exposes_owner_protection_and_entries():
    a = parse_sddl(ACCEPT["protected-user-system-admins"])
    assert a.owner == USER and a.protected and [x.sid for x in a.aces] == [USER, SYSTEM_SID, ADMINISTRATORS_SID]
    assert not parse_sddl(REFUSE["inherited-everyone"][0]).protected


# ---- PLATFORM-NEUTRAL: creation order and failure handling (fake ACL helper) -------------------------------------------------------------------------
class FakeAcl:
    """Stands in for WindowsAcl and records what happens to the file and in which order. Starts no process."""

    def __init__(self, *, restrict_fails=False, review=None):
        self.events: list[str] = []
        self.restrict_fails, self.verdict = restrict_fails, review or []
        self.size_at_restrict: int | None = None

    def restrict(self, path):
        self.events.append("restrict")
        self.size_at_restrict = os.path.getsize(path)               # the key must NOT be in the file yet
        if self.restrict_fails:
            raise OSError("icacls failed (exit 5)")

    def review(self, path):
        self.events.append("review")
        return list(self.verdict)


def strays(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name.endswith(".tmp"))


def test_acl_is_applied_and_verified_before_the_key_is_written(tmp_path):
    acl = FakeAcl()
    key = load_key({}, tmp_path / "keys" / "k", acl=acl)
    assert len(key) == 32 and acl.events == ["restrict", "review", "review"]            # restrict, verify the tmp file, verify the published file again at load
    assert acl.size_at_restrict == 0                                                      # the secret did not exist while the ACL was still the inherited one
    assert strays(tmp_path / "keys") == []


def test_if_the_acl_can_not_be_restricted_no_key_is_written(tmp_path):
    with pytest.raises(IntegrityError, match="could not be restricted"):
        load_key({}, tmp_path / "keys" / "k", acl=FakeAcl(restrict_fails=True))
    assert not (tmp_path / "keys" / "k").exists() and strays(tmp_path / "keys") == []


def test_if_the_acl_is_still_broad_after_restricting_no_key_is_written(tmp_path):
    with pytest.raises(IntegrityError, match="unacceptable ACL"):
        load_key({}, tmp_path / "keys" / "k", acl=FakeAcl(review=["access is granted to Everyone"]))
    assert not (tmp_path / "keys" / "k").exists() and strays(tmp_path / "keys") == []


def test_an_existing_key_file_with_a_broad_acl_is_refused_and_never_modified(tmp_path):
    k = tmp_path / "k"
    k.write_text("ab" * 32, encoding="ascii")
    if not WIN:
        k.chmod(0o600)
    acl = FakeAcl(review=["access is granted to BUILTIN\\Users (S-1-5-32-545)"])
    before = k.read_bytes()
    with pytest.raises(IntegrityError, match="ACL is not acceptable.*BUILTIN.Users.*never changed automatically"):
        load_key({}, k, acl=acl)
    assert acl.events == ["review"] and k.read_bytes() == before                         # reviewed only: restrict() is never called for a file we did not create


def test_an_existing_acceptable_key_file_is_read_without_touching_it(tmp_path):
    k = tmp_path / "k"
    k.write_text("cd" * 32, encoding="ascii")
    if not WIN:
        k.chmod(0o600)
    acl = FakeAcl()
    assert load_key({}, k, acl=acl) == bytes.fromhex("cd" * 32) and acl.events == ["review"]


def test_the_acl_review_failing_to_read_is_a_refusal(tmp_path):
    def run(argv):
        return 1, "Get-Acl : Access is denied"
    k = tmp_path / "k"
    k.write_text("cd" * 32, encoding="ascii")
    if not WIN:
        k.chmod(0o600)
    with pytest.raises(IntegrityError, match="ACL could not be read"):
        load_key({}, k, acl=WindowsAcl(run))


def test_a_failed_publish_is_reported_and_leaves_nothing_behind(tmp_path, monkeypatch):
    def refuse(src, dst):
        raise PermissionError(13, "no hard links here")
    monkeypatch.setattr(store_mod.os, "link", refuse)
    with pytest.raises(IntegrityError, match="published atomically"):
        load_key({}, tmp_path / "keys" / "k", acl=FakeAcl())
    assert not (tmp_path / "keys" / "k").exists() and strays(tmp_path / "keys") == []


def test_if_another_process_publishes_first_its_key_is_used(tmp_path, monkeypatch):
    real_link = os.link

    def lose_the_race(src, dst):
        Path(dst).write_text("ef" * 32, encoding="ascii")          # somebody else published first ...
        if os.name == "posix":
            Path(dst).chmod(0o600)
        return real_link(src, dst)                                  # ... so the exclusive publish raises FileExistsError
    monkeypatch.setattr(store_mod.os, "link", lose_the_race)
    assert load_key({}, tmp_path / "keys" / "k", acl=FakeAcl()) == bytes.fromhex("ef" * 32) and strays(tmp_path / "keys") == []


def test_empty_or_truncated_key_file_fails_closed(tmp_path):
    k = tmp_path / "k"
    k.write_text("", encoding="ascii")
    if not WIN:
        k.chmod(0o600)
    with pytest.raises(IntegrityError, match="too short"):
        load_key({}, k, acl=FakeAcl())
    k.write_text("ab" * 31, encoding="ascii")
    with pytest.raises(IntegrityError, match="too short"):
        load_key({}, k, acl=FakeAcl())


def test_concurrent_first_starts_in_real_processes_agree_on_one_key(tmp_path):
    """Real processes race to create the key file: all must return the SAME key, nobody may see an empty/half file, no temp files may remain."""
    script = tmp_path / "creator.py"
    script.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {SRC!r})
        from jarvis.self_improvement.store import load_key
        print(load_key({{}}, sys.argv[1]).hex())
    """))
    target = tmp_path / "keys" / "k"
    procs = [subprocess.Popen([sys.executable, str(script), str(target)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    outs = [p.communicate(timeout=120) for p in procs]
    assert [p.returncode for p in procs] == [0, 0, 0, 0], [o[1][-300:] for o in outs]
    keys = {o[0].strip() for o in outs}
    assert len(keys) == 1 and len(next(iter(keys))) == 64
    assert bytes.fromhex(next(iter(keys))) == load_key({}, target) and strays(target.parent) == []


@pytest.mark.skipif(WIN, reason="POSIX mode bits; the Windows equivalent is the ACL tests below")
def test_posix_mode_bits_are_checked_and_new_keys_are_owner_only(tmp_path):
    k = tmp_path / "keys" / "k"
    load_key({}, k)
    assert k.stat().st_mode & 0o777 == 0o600
    k.chmod(0o640)
    with pytest.raises(IntegrityError, match="group/others"):
        load_key({}, k)


# ---- WINDOWS ONLY: the real mechanism ----------------------------------------------------------------------------------------------------------------
windows_only = pytest.mark.skipif(not WIN, reason="uses the real Windows ACL machinery (PowerShell Get-Acl, icacls); not applicable elsewhere")


def system32() -> str:
    return os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32")


def ps(script: str) -> str:
    """Independent of the production code: run a PowerShell snippet and return stdout."""
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    exe = os.path.join(system32(), "WindowsPowerShell", "v1.0", "powershell.exe")
    r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout


def acl_facts(path: Path) -> dict:
    out = ps("$a = Get-Acl -LiteralPath '%s'; "
             "'PROTECTED=' + $a.AreAccessRulesProtected; "
             "'OWNER=' + $a.GetOwner([System.Security.Principal.SecurityIdentifier]).Value; "
             "$a.Access | ForEach-Object { 'ACE=' + $_.AccessControlType + ',' + $_.IsInherited + ',' + $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value }"
             % str(path).replace("'", "''"))
    facts = {"protected": "PROTECTED=True" in out, "owner": re.search(r"OWNER=(\S+)", out).group(1), "aces": []}
    for m in re.finditer(r"ACE=(\w+),(\w+),(S-\S+)", out):
        facts["aces"].append((m.group(1), m.group(2) == "True", m.group(3)))
    return facts


def current_user_sid() -> str:
    return ps("[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value").strip()


def icacls(*args: str) -> None:
    r = subprocess.run([os.path.join(system32(), "icacls.exe"), *args], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


BROAD = {"S-1-1-0", "S-1-5-32-545", "S-1-5-11", "S-1-5-4", "S-1-5-2"}          # Everyone, Users, Authenticated Users, Interactive, Network


@windows_only
def test_win_created_key_is_restricted_to_user_system_and_administrators(tmp_path):
    k = tmp_path / "keys" / "k"
    key = load_key({}, k)                                            # real WindowsAcl: PowerShell + icacls
    facts, me = acl_facts(k), current_user_sid()
    allow = {sid for kind, _, sid in facts["aces"] if kind == "Allow"}
    assert len(key) == 32 and facts["protected"], facts              # inheritance removed
    assert allow and allow <= {me, SYSTEM_SID, ADMINISTRATORS_SID}, facts
    assert not any(inherited for _, inherited, _ in facts["aces"]), facts
    assert facts["owner"] in {me, ADMINISTRATORS_SID}, facts
    assert me in allow or ADMINISTRATORS_SID in allow                # legitimate access is not locked out
    assert load_key({}, k) == key                                    # reading it back (second start) works and passes the review
    assert strays(k.parent) == []


@windows_only
def test_win_key_created_inside_a_folder_that_grants_everyone_does_not_inherit_it(tmp_path):
    folder = tmp_path / "shared"
    folder.mkdir()
    icacls(str(folder), "/grant", "*S-1-1-0:(OI)(CI)(R)", "*S-1-5-32-545:(OI)(CI)(R)")   # the folder (inside tmp_path) lets Everyone and Users read new files
    probe = folder / "probe.txt"
    probe.write_text("x")
    assert BROAD & {sid for _, _, sid in acl_facts(probe)["aces"]}, "precondition: files in this folder do inherit broad access"
    k = folder / "k"
    load_key({}, k)
    facts = acl_facts(k)
    assert not (BROAD & {sid for _, _, sid in facts["aces"]}), facts
    assert facts["protected"], facts


@windows_only
def test_win_existing_key_with_inherited_broad_access_is_refused_and_not_modified(tmp_path):
    folder = tmp_path / "shared"
    folder.mkdir()
    icacls(str(folder), "/grant", "*S-1-1-0:(OI)(CI)(R)")
    k = folder / "k"
    k.write_text("ab" * 32, encoding="ascii")                        # created by the test, NOT by load_key: inherits Everyone
    before, acl_before = k.read_bytes(), acl_facts(k)
    assert "S-1-1-0" in {sid for _, _, sid in acl_before["aces"]}
    with pytest.raises(IntegrityError, match="ACL is not acceptable.*Everyone"):
        load_key({}, k)
    assert k.read_bytes() == before and acl_facts(k) == acl_before   # an existing file is never changed automatically


@windows_only
@pytest.mark.parametrize("sid, name", [("S-1-5-32-545", "Users"), ("S-1-5-11", "Authenticated Users"), ("S-1-1-0", "Everyone")])
def test_win_explicit_grant_to_a_broad_group_is_refused(tmp_path, sid, name):
    k = tmp_path / "k"
    load_key({}, k)                                                  # a correct key first ...
    icacls(str(k), "/grant", f"*{sid}:(R)")                          # ... then somebody widens it
    with pytest.raises(IntegrityError, match=name):
        load_key({}, k)


@windows_only
def test_win_removing_inheritance_alone_is_not_enough_if_explicit_broad_entries_remain(tmp_path):
    k = tmp_path / "k"
    k.write_text("ab" * 32, encoding="ascii")
    icacls(str(k), "/inheritance:d", "/grant", "*S-1-5-32-545:(R)")  # copy inherited entries, add Users
    with pytest.raises(IntegrityError, match="Users"):
        load_key({}, k)


@windows_only
def test_win_helper_reports_the_real_user_and_sddl(tmp_path):
    from jarvis.self_improvement.store import _default_windows_acl
    f = tmp_path / "f"
    f.write_text("x")
    user, sddl = _default_windows_acl().read(str(f))
    assert user == current_user_sid() and sddl.startswith(("O:", "G:", "D:"))
    with pytest.raises(OSError):
        _default_windows_acl().read(str(tmp_path / "does-not-exist"))
    assert _default_windows_acl().review(str(tmp_path / "does-not-exist"))           # unreadable = a problem, never a pass
