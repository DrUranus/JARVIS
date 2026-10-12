"""V4: the proposal store is not trusted merely because it is a file. HMAC integrity, tamper handling, compare-and-swap, concurrent threads and processes,
key handling, and startup checks of the data directory and key location."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.config import load_settings
from jarvis.self_improvement import (ConcurrentUpdateError, IntegrityError, JsonProposalStore, MemoryProposalStore, Proposal, ProposalStatus as S, UnknownProposalError)
from jarvis.self_improvement.factory import build_self_improvement
from jarvis.self_improvement.models import Approval, utcnow
from jarvis.self_improvement.store import load_key
from si_util import PLANNER

KEY = b"k" * 32
SRC = Path(__file__).resolve().parent.parent / "src"


def prop(title="t", **kw) -> Proposal:
    return Proposal(title, "problem", source="user", **kw)


def store(tmp_path, key=KEY) -> JsonProposalStore:
    return JsonProposalStore(tmp_path / "d" / "proposals.json", key)


def raw(tmp_path):
    return json.loads((tmp_path / "d" / "proposals.json").read_text(encoding="utf-8"))


def write_raw(tmp_path, doc):
    (tmp_path / "d" / "proposals.json").write_text(json.dumps(doc), encoding="utf-8")


# ---- roundtrip and compare-and-swap ---------------------------------------------------------------------------------------------------------
def test_roundtrip_and_revision_counter(tmp_path):
    st = store(tmp_path)
    a = st.save(prop("a"))
    assert a.rev == 1 and st.get(a.proposal_id).to_dict() == a.to_dict()
    b = st.save(a.moved(S.PROPOSED, "user"))
    assert b.rev == 2 and JsonProposalStore(tmp_path / "d" / "proposals.json", KEY).get(a.proposal_id).status is S.PROPOSED
    with pytest.raises(UnknownProposalError):
        st.get("imp-000000000000")


@pytest.mark.parametrize("make", [lambda tmp: MemoryProposalStore(), lambda tmp: store(tmp)], ids=["memory", "json"])
def test_stale_copies_cannot_overwrite_newer_state(tmp_path, make):
    st = make(tmp_path)
    first = st.save(prop())
    mover = st.save(first.moved(S.PROPOSED, "user"))
    with pytest.raises(ConcurrentUpdateError):
        st.save(first.moved(S.REJECTED, "user", "stale"))          # written from a copy that was read before `mover`
    assert st.get(first.proposal_id).status is S.PROPOSED and st.get(first.proposal_id).rev == mover.rev
    with pytest.raises(ConcurrentUpdateError):
        st.save(replace(prop("new"), rev=3))                        # a new proposal must start at rev 0


@pytest.mark.parametrize("make", [lambda tmp: MemoryProposalStore(), lambda tmp: store(tmp)], ids=["memory", "json"])
def test_concurrent_threads_never_lose_an_update(tmp_path, make):
    st = make(tmp_path)
    shared = st.save(prop("shared"))
    wins, lock = [], threading.Lock()

    def work(n):
        for _ in range(10):
            cur = st.get(shared.proposal_id)
            try:
                st.save(cur.evolve(title=f"t{n}"))
                with lock:
                    wins.append(n)
            except ConcurrentUpdateError:
                pass
            st.save(prop(f"own-{n}"))

    ts = [threading.Thread(target=work, args=(i,)) for i in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert st.get(shared.proposal_id).rev == 1 + len(wins)          # every successful CAS is counted exactly once: no lost update
    assert len([p for p in st.list() if p.title.startswith("own-")]) == 60


def test_concurrent_processes_never_lose_an_update(tmp_path):
    path = tmp_path / "d" / "proposals.json"
    st = JsonProposalStore(path, KEY)
    shared = st.save(prop("shared"))
    script = tmp_path / "worker.py"
    script.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(SRC)!r})
        from jarvis.self_improvement import JsonProposalStore, ConcurrentUpdateError, Proposal
        n = sys.argv[1]
        st = JsonProposalStore({str(path)!r}, {KEY!r})
        wins = 0
        for i in range(8):
            while True:
                cur = st.get({shared.proposal_id!r})
                try:
                    st.save(cur.evolve(title="w" + n)); wins += 1; break
                except ConcurrentUpdateError:
                    continue
            st.save(Proposal("own-" + n, "p", source="user"))
        print(wins)
    """))
    procs = [subprocess.Popen([sys.executable, str(script), str(i)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(4)]
    outs = [p.communicate(timeout=120) for p in procs]
    assert all(p.returncode == 0 for p in procs), [o[1][-300:] for o in outs]
    st2 = JsonProposalStore(path, KEY)
    assert st2.get(shared.proposal_id).rev == 1 + sum(int(o[0]) for o in outs) == 1 + 32 and len([p for p in st2.list() if p.title.startswith("own-")]) == 32


# ---- tamper detection (fail closed) ----------------------------------------------------------------------------------------------------------
def untouched_and_unusable(tmp_path, st):
    before = (tmp_path / "d" / "proposals.json").read_bytes()
    with pytest.raises(IntegrityError):
        st.list()
    with pytest.raises(IntegrityError):
        st.get("imp-000000000000")
    with pytest.raises(IntegrityError):
        st.save(prop("another"))
    assert (tmp_path / "d" / "proposals.json").read_bytes() == before                         # never "repaired" or overwritten
    assert (tmp_path / "d" / "proposals.json.tampered").read_bytes() == before


def make_approved(tmp_path):
    st = store(tmp_path)
    p = st.save(prop())
    p = st.save(p.moved(S.PROPOSED, "user"))
    return st, p


def test_edited_status_is_detected(tmp_path):
    st, p = make_approved(tmp_path)
    doc = raw(tmp_path)
    doc["proposals"][0]["status"] = "APPROVED"
    write_raw(tmp_path, doc)
    untouched_and_unusable(tmp_path, st)


def test_forged_approval_entry_is_detected(tmp_path):
    st, p = make_approved(tmp_path)
    doc = raw(tmp_path)
    doc["proposals"][0]["status"] = "APPROVED"
    doc["proposals"][0]["approval"] = Approval(utcnow(), "forged", "a" * 40, "b" * 32, "c" * 32).to_dict()
    write_raw(tmp_path, doc)
    untouched_and_unusable(tmp_path, st)


@pytest.mark.parametrize("edit", [
    lambda d: d["proposals"].append(d["proposals"][0] | {"proposal_id": "imp-aaaaaaaaaaaa"}),
    lambda d: d["proposals"].clear(), lambda d: d.__setitem__("seq", d["seq"] + 1), lambda d: d.__setitem__("format", 1), lambda d: d.pop("mac"),
    lambda d: d.__setitem__("mac", "0" * 64), lambda d: d["proposals"][0].__setitem__("rev", 99), lambda d: d["proposals"][0].__setitem__("title", "other")],
    ids=["added", "cleared", "seq", "format", "no-mac", "bad-mac", "rev", "title"])
def test_any_edit_of_the_signed_document_is_detected(tmp_path, edit):
    st, _ = make_approved(tmp_path)
    doc = raw(tmp_path)
    edit(doc)
    write_raw(tmp_path, doc)
    untouched_and_unusable(tmp_path, st)


def test_a_wrong_key_or_garbage_or_truncation_is_detected(tmp_path):
    st, _ = make_approved(tmp_path)
    wrong = JsonProposalStore(tmp_path / "d" / "proposals.json", b"x" * 32)
    assert "integrity" in wrong.load_warning
    with pytest.raises(IntegrityError):
        wrong.list()
    f = tmp_path / "d" / "proposals.json"
    f.write_text("{ not json", encoding="utf-8")
    with pytest.raises(IntegrityError):
        st.list()
    assert f.read_text(encoding="utf-8") == "{ not json"
    f.write_bytes(f.read_bytes()[:10])
    with pytest.raises(IntegrityError):
        st.list()


def test_path_and_hash_manipulation_is_refused_even_with_a_valid_signature(tmp_path):
    """Someone WITH the key writes bad fields: the records are still validated when loaded (defence in depth)."""
    import hashlib
    import hmac
    st, p = make_approved(tmp_path)
    good = raw(tmp_path)
    good.pop("mac")
    for field, value in (("base_commit", "--output=/tmp/x"), ("head_commit", "g" * 40), ("branch", "main"), ("changed_files", ["src/jarvis/permissions/engine.py"]),
                         ("changed_files", ["../x.py"]), ("diff_digest", "zz"), ("suggested_tests", ["../../etc/passwd"]), ("status", "NOPE"), ("proposal_id", "../../x")):
        doc = json.loads(json.dumps(good))
        doc["proposals"][0][field] = value
        doc["mac"] = hmac.new(KEY, json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii"), hashlib.sha256).hexdigest()
        write_raw(tmp_path, doc)
        with pytest.raises(IntegrityError):
            JsonProposalStore(tmp_path / "d" / "proposals.json", KEY).list()


def test_older_signed_file_is_a_detected_rollback_within_a_process(tmp_path):
    st = store(tmp_path)
    a = st.save(prop("a"))
    old = (tmp_path / "d" / "proposals.json").read_bytes()
    st.save(prop("b"))
    (tmp_path / "d" / "proposals.json").write_bytes(old)
    with pytest.raises(IntegrityError, match="older"):
        st.list()
    assert a                     # (a replay after a restart is NOT detected: documented limit)


def test_a_missing_file_is_an_empty_store_not_an_error(tmp_path):
    assert store(tmp_path).list() == []


def test_store_needs_a_strong_key(tmp_path):
    with pytest.raises(IntegrityError):
        JsonProposalStore(tmp_path / "p.json", b"short")


# ---- key handling and startup checks ---------------------------------------------------------------------------------------------------------
def test_key_file_is_created_owner_only_and_reused(tmp_path):
    kp = tmp_path / "keys" / "k"
    k1 = load_key({}, kp)
    assert len(k1) == 32 and load_key({}, kp) == k1
    if os.name == "posix":
        assert kp.stat().st_mode & 0o077 == 0
        kp.chmod(0o644)
        with pytest.raises(IntegrityError, match="group"):
            load_key({}, kp)


def test_key_from_environment_and_bad_keys(tmp_path):
    assert load_key({"JARVIS_SELF_IMPROVEMENT_STORE_KEY": "ab" * 32}, tmp_path / "unused") == bytes.fromhex("ab" * 32)
    for bad in ("zz" * 32, "ab" * 8):
        with pytest.raises(IntegrityError):
            load_key({"JARVIS_SELF_IMPROVEMENT_STORE_KEY": bad}, tmp_path / "unused")
    kp = tmp_path / "k"
    kp.write_text("nothex", encoding="ascii")
    kp.chmod(0o600)
    with pytest.raises(IntegrityError):
        load_key({}, kp)


def settings_for(tmp_path, **extra):
    env = {"JARVIS_WORKSPACE": str(tmp_path / "ws"), "JARVIS_LOG_DIR": str(tmp_path / "logs"), "JARVIS_MEMORY_PATH": str(tmp_path / "m.db"),
           "JARVIS_SELF_IMPROVEMENT_ENABLED": "true", "JARVIS_SELF_IMPROVEMENT_DATA_DIR": str(tmp_path / "improve"), "JARVIS_SELF_IMPROVEMENT_KEY_PATH": str(tmp_path / "keys" / "k"), **extra}
    return load_settings(env={k: str(v) for k, v in env.items()})


def test_startup_accepts_a_data_dir_and_key_outside_the_tool_roots(tmp_path):
    sub = build_self_improvement(settings_for(tmp_path), env={})
    assert sub.available and sub.manager.describe()["code_execution"] is False
    assert (tmp_path / "keys" / "k").exists()


@pytest.mark.parametrize("data, key, text", [
    ("ws/improve", "keys/k", "data_dir"), ("ws", "keys/k", "data_dir"), ("", "keys/k", "data_dir"), ("improve", "ws/k", "store key"), ("improve", "improve/k", "inside the data"),
    ("logs/improve", "keys/k", "data_dir")])
def test_startup_fails_closed_when_data_dir_or_key_are_where_tools_can_write(tmp_path, data, key, text):
    (tmp_path / "ws").mkdir()
    s = settings_for(tmp_path, JARVIS_SELF_IMPROVEMENT_DATA_DIR=tmp_path / data if data else tmp_path, JARVIS_SELF_IMPROVEMENT_KEY_PATH=tmp_path / key)
    sub = build_self_improvement(s, env={})
    assert not sub.available and sub.status == "disabled" and text in sub.reason


def test_startup_checks_the_coding_roots_and_allowed_roots(tmp_path):
    other = tmp_path / "project"
    other.mkdir()
    for var in ("JARVIS_SECURITY_ALLOWED_ROOTS", "JARVIS_CODING_WORKSPACE_ROOTS"):
        s = settings_for(tmp_path, JARVIS_SELF_IMPROVEMENT_DATA_DIR=other / "data", **{var: str(other)})
        sub = build_self_improvement(s, env={})
        assert not sub.available and "data_dir" in sub.reason, var


def test_startup_with_a_broken_key_or_tampered_store_stays_unusable(tmp_path):
    s = settings_for(tmp_path)
    sub = build_self_improvement(s, env={"JARVIS_SELF_IMPROVEMENT_STORE_KEY": "ab" * 4})
    assert not sub.available and "could not be built" in sub.reason
    good = build_self_improvement(s, env={})
    good.manager.propose("t", "p")
    f = tmp_path / "improve" / "proposals.json"
    doc = json.loads(f.read_text(encoding="utf-8"))
    doc["proposals"][0]["status"] = "APPROVED"
    f.write_text(json.dumps(doc), encoding="utf-8")
    again = build_self_improvement(s, env={})
    assert again.available and "integrity" in again.warning
    with pytest.raises(IntegrityError):
        again.manager.list()
