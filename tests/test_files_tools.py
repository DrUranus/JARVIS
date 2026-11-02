"""File tools (A8): real PermissionEngine + real ToolRegistry + real (temporary) files. No network, no real keys.

Covers: roots / protected paths / no delete / no symlink bypass (incl. abuse), hash-guarded writes with preview, organize (plan first,
every step confirmed), emergency stop, budget, default off. Symlink tests are skipped where the OS cannot create links (Windows without
the privilege): the CI Windows run is the platform proof, not this Linux run."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from jarvis.config import FilesSettings, Settings
from jarvis.files import FilesController, FilesError
from jarvis.files.factory import baseline_rules, build_files
from jarvis.files.tools import register_files_tools
from jarvis.permissions import ConfirmationChoice, Policy, ResourceType
from jarvis.permissions.budget import SessionBudget
from jarvis.tools import ToolRegistry
from secutil import make_engine

ONCE, SESSION, NO = ConfirmationChoice.ALLOW_ONCE, ConfirmationChoice.ALLOW_SESSION, ConfirmationChoice.DENY


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass
class Rig:
    engine: Any
    ws: Path
    prompts: Any
    registry: ToolRegistry
    controller: FilesController
    outside: Path
    sink: Any = None

    def run(self, **kw: Any):
        return self.registry.execute("files", **kw)

    def ok(self, **kw: Any) -> Any:
        out = self.run(**kw)
        assert out.success, (kw, out.error)
        return out.output

    def bad(self, **kw: Any) -> str:
        out = self.run(**kw)
        assert not out.success, (kw, out.output)
        return out.error or ""


def make_rig(tmp_path: Path, answers=(), engine_kw: dict | None = None, protected=(), **settings_kw: Any) -> Rig:
    from jarvis.permissions import ScriptedConfirmation
    tmp_path.mkdir(parents=True, exist_ok=True)
    prompts = ScriptedConfirmation(answers)
    engine, sink, ws = make_engine(tmp_path, confirmation=prompts, protected=[tmp_path / "ws" / "prot"] if protected else (),
                                    **(engine_kw or {}))
    ws = Path(os.path.realpath(ws))
    outside = Path(os.path.realpath(tmp_path)) / "outside"
    outside.mkdir()
    settings = FilesSettings(enabled=True, **settings_kw)
    controller = FilesController(engine.guard, settings, roots=(str(ws),))
    engine.update_policy(Policy(tuple(engine.policy.rules) + tuple(baseline_rules(settings))))
    registry = ToolRegistry(engine)
    register_files_tools(registry, controller)
    return Rig(engine, ws, prompts, registry, controller, outside, sink)


def can_symlink(tmp: Path) -> bool:
    try:
        (tmp / "_probe").symlink_to(tmp, target_is_directory=True)
        (tmp / "_probe").unlink()
        return True
    except (OSError, NotImplementedError):
        return False


# ---- default off / wiring --------------------------------------------------------------------------------------------------------
def test_default_is_off_and_registers_nothing(tmp_path):
    assert Settings().files.enabled is False
    engine, _s, _ws = make_engine(tmp_path)
    reg = ToolRegistry(engine)
    sub = build_files(Settings(), reg, engine)
    assert sub.status == "disabled" and not sub.available
    assert "files" not in reg
    assert reg.execute("files", action="list", path=str(tmp_path)).success is False


def test_enabled_builds_tool_and_halt_resume(tmp_path):
    engine, _s, ws = make_engine(tmp_path)
    reg = ToolRegistry(engine)
    sub = build_files(Settings(files=FilesSettings(enabled=True, roots=(str(ws),))), reg, engine)
    assert sub.status == "enabled" and sub.tool_names == ["files"]
    assert sub.halt("t") and sub.describe()["status"] == "halted"
    assert sub.resume() and sub.describe()["status"] == "enabled"


def test_roots_outside_the_engine_roots_are_dropped(tmp_path):
    engine, _s, ws = make_engine(tmp_path)
    sub = build_files(Settings(files=FilesSettings(enabled=True, roots=(str(tmp_path),))), ToolRegistry(engine), engine)
    assert sub.status == "unavailable"          # nothing confirmed by the engine is left: fail closed


# ---- read side (GREEN) ----------------------------------------------------------------------------------------------------------
def test_list_and_read_are_green_and_bounded(tmp_path):
    r = make_rig(tmp_path, max_read_chars=200, max_list_entries=3)
    for i in range(5):
        (r.ws / f"f{i}.txt").write_text("x" * 50, encoding="utf-8")
    (r.ws / "big.txt").write_text("y" * 5000, encoding="utf-8")
    out = r.ok(action="list", path=str(r.ws))
    assert len(out["entries"]) == 3 and out["truncated"] is True
    got = r.ok(action="read", path=str(r.ws / "big.txt"))
    assert len(got["content"]) <= 200 and got["truncated"] is True and got["sha256"] == sha("y" * 5000)
    assert r.prompts.requests == []             # reading never asks


def test_read_relative_to_first_root_and_redacts_secrets(tmp_path):
    r = make_rig(tmp_path)
    (r.ws / "n.txt").write_text("key sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789 end", encoding="utf-8")
    out = r.ok(action="read", path="n.txt")
    assert "abcdefghijklmnop" not in out["content"] and out["secrets_redacted"] is True


def test_secret_and_git_files_are_never_read(tmp_path):
    r = make_rig(tmp_path)
    (r.ws / ".env").write_text("A=1", encoding="utf-8")
    (r.ws / ".git").mkdir()
    (r.ws / ".git" / "config").write_text("x", encoding="utf-8")
    (r.ws / "id_rsa").write_text("x", encoding="utf-8")
    for name in (".env", ".git/config", "id_rsa"):
        assert "protected" in r.bad(action="read", path=name).lower() or "blocked" in r.bad(action="read", path=name).lower()
    names = [e["name"] for e in r.ok(action="list", path=str(r.ws))["entries"]]
    assert ".env" not in names and ".git" not in names and "id_rsa" not in names


def test_binary_file_is_not_read_as_text(tmp_path):
    r = make_rig(tmp_path)
    (r.ws / "b.dat").write_bytes(b"\x00\x01\x02")
    assert "binary" in r.bad(action="read", path="b.dat").lower()


# ---- create / write: YELLOW with preview, hash-guarded ----------------------------------------------------------------------
def test_create_asks_with_preview_and_creates(tmp_path):
    r = make_rig(tmp_path, [ONCE])
    r.ok(action="create", path="a.txt", content="hallo\nwelt\n")
    assert (r.ws / "a.txt").read_text(encoding="utf-8") == "hallo\nwelt\n"
    req = r.prompts.requests[0]
    assert req.level.value == "yellow" and "hallo" in " ".join(req.context.values())


def test_create_denied_by_user_changes_nothing(tmp_path):
    r = make_rig(tmp_path, [NO])
    r.bad(action="create", path="a.txt", content="x")
    assert not (r.ws / "a.txt").exists() and len(r.prompts.requests) == 1


def test_create_never_overwrites(tmp_path):
    r = make_rig(tmp_path, [ONCE, ONCE])
    (r.ws / "a.txt").write_text("alt", encoding="utf-8")
    assert "exists" in r.bad(action="create", path="a.txt", content="neu").lower()
    assert (r.ws / "a.txt").read_text(encoding="utf-8") == "alt"


def test_write_needs_expected_hash_and_matches_it(tmp_path):
    r = make_rig(tmp_path, [ONCE, ONCE, ONCE])
    f = r.ws / "a.txt"
    f.write_text("alt\n", encoding="utf-8")
    assert "expected_sha256" in r.bad(action="write", path="a.txt", content="neu\n")
    assert "changed" in r.bad(action="write", path="a.txt", content="neu\n", expected_sha256=sha("anderer inhalt")).lower()
    assert f.read_text(encoding="utf-8") == "alt\n"
    out = r.ok(action="write", path="a.txt", content="neu\n", expected_sha256=sha("alt\n"))
    assert f.read_text(encoding="utf-8") == "neu\n" and out["sha256"] == sha("neu\n") and out["old_sha256"] == sha("alt\n")
    req = r.prompts.requests[-1]
    assert req.level.value == "yellow" and "neu" in " ".join(req.context.values())


def test_write_refused_when_file_changed_after_preview(tmp_path):
    r = make_rig(tmp_path)
    f = r.ws / "a.txt"
    f.write_text("alt\n", encoding="utf-8")
    kw = dict(path="a.txt", content="neu\n", expected_sha256=sha("alt\n"))
    r.controller.plan("write", phase="describe", **kw)
    f.write_text("jemand anderes\n", encoding="utf-8")
    with pytest.raises(FilesError) as e:
        r.controller.plan("write", phase="perform", **kw)
    assert e.value.code == "file_changed" and f.read_text(encoding="utf-8") == "jemand anderes\n"


def test_write_without_preview_is_refused(tmp_path):
    r = make_rig(tmp_path)
    (r.ws / "a.txt").write_text("alt\n", encoding="utf-8")
    with pytest.raises(FilesError) as e:
        r.controller.plan("write", phase="perform", path="a.txt", content="x", expected_sha256=sha("alt\n"))
    assert e.value.code == "file_changed"


def test_execute_without_engine_grant_is_refused(tmp_path):
    r = make_rig(tmp_path)
    plan = r.controller.plan("create", path="a.txt", content="x")
    with pytest.raises(FilesError) as e:
        r.controller.execute(plan)
    assert e.value.code == "not_authorized" and not (r.ws / "a.txt").exists()


def test_secrets_are_never_written_and_files_with_secrets_not_rewritten(tmp_path):
    r = make_rig(tmp_path, [ONCE, ONCE])
    key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"
    assert "secret" in r.bad(action="create", path="a.txt", content=f"k={key}").lower()
    (r.ws / "b.txt").write_text(f"k={key}\n", encoding="utf-8")
    assert "secret" in r.bad(action="write", path="b.txt", content="ok\n", expected_sha256=sha(f"k={key}\n")).lower()
    assert not (r.ws / "a.txt").exists() and key in (r.ws / "b.txt").read_text(encoding="utf-8")


def test_dangerous_file_types_and_secret_names_cannot_be_created(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 4)
    for name in ("evil.exe", ".env", "x.pem", ".git/config"):
        r.bad(action="create", path=name, content="x")
        assert not (r.ws / name).exists()


# ---- move / copy / mkdir -----------------------------------------------------------------------------------------------------------
def test_move_copy_mkdir_work_and_ask(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3)
    (r.ws / "a.txt").write_text("A", encoding="utf-8")
    r.ok(action="mkdir", path="sub")
    r.ok(action="copy", path="a.txt", destination="sub/b.txt")
    r.ok(action="move", path="a.txt", destination="sub/c.txt")
    assert not (r.ws / "a.txt").exists()
    assert (r.ws / "sub" / "b.txt").read_text(encoding="utf-8") == "A" and (r.ws / "sub" / "c.txt").read_text(encoding="utf-8") == "A"
    assert len(r.prompts.requests) == 3 and all(q.level.value == "yellow" for q in r.prompts.requests)
    assert "a.txt" in " ".join(r.prompts.requests[2].context.values())      # the preview names source and destination


def test_move_and_copy_never_overwrite(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 4)
    (r.ws / "a.txt").write_text("A", encoding="utf-8")
    (r.ws / "b.txt").write_text("B", encoding="utf-8")
    assert "exists" in r.bad(action="move", path="a.txt", destination="b.txt").lower()
    assert "exists" in r.bad(action="copy", path="a.txt", destination="b.txt").lower()
    assert (r.ws / "a.txt").read_text(encoding="utf-8") == "A" and (r.ws / "b.txt").read_text(encoding="utf-8") == "B"


def test_move_into_itself_and_of_a_root_is_refused(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3)
    (r.ws / "d").mkdir()
    r.bad(action="move", path="d", destination="d/inner")
    r.bad(action="move", path=str(r.ws), destination=str(r.ws / "x"))
    assert (r.ws / "d").is_dir()


def test_source_and_destination_must_both_be_inside_roots(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 6)
    (r.ws / "a.txt").write_text("A", encoding="utf-8")
    (r.outside / "o.txt").write_text("O", encoding="utf-8")
    r.bad(action="move", path="a.txt", destination=str(r.outside / "a.txt"))
    r.bad(action="copy", path="a.txt", destination=str(r.outside / "a.txt"))
    r.bad(action="move", path=str(r.outside / "o.txt"), destination="o.txt")
    r.bad(action="copy", path=str(r.outside / "o.txt"), destination="o.txt")
    r.bad(action="read", path=str(r.outside / "o.txt"))
    assert (r.ws / "a.txt").exists() and (r.outside / "o.txt").exists() and not (r.outside / "a.txt").exists()


def test_sibling_directory_with_same_prefix_is_outside(tmp_path):
    r = make_rig(tmp_path, [ONCE])
    evil = Path(str(r.ws) + "-evil")
    evil.mkdir()
    r.bad(action="create", path=str(evil / "x.txt"), content="x")
    assert not (evil / "x.txt").exists()


def test_protected_paths_of_the_engine_are_never_modified(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 4, protected=True)
    prot = r.ws / "prot"
    prot.mkdir()
    (prot / "policy.toml").write_text("p", encoding="utf-8")
    (r.ws / "a.txt").write_text("A", encoding="utf-8")
    r.bad(action="create", path="prot/new.txt", content="x")
    r.bad(action="move", path="prot/policy.toml", destination="gone.toml")        # the SOURCE is protected, not the destination
    r.bad(action="move", path="a.txt", destination="prot/a.txt")
    r.bad(action="write", path="prot/policy.toml", content="x", expected_sha256=sha("p"))
    assert (prot / "policy.toml").read_text(encoding="utf-8") == "p" and not (prot / "new.txt").exists() and (r.ws / "a.txt").exists()


# ---- no delete / path spelling --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("action", ["delete", "remove", "rm", "unlink", "rmdir", "trash", "erase", "DELETE", "overwrite", "run", ""])
def test_there_is_no_delete_or_other_action(tmp_path, action):
    r = make_rig(tmp_path, [ONCE] * 2)
    (r.ws / "a.txt").write_text("A", encoding="utf-8")
    r.bad(action=action, path="a.txt")
    assert (r.ws / "a.txt").read_text(encoding="utf-8") == "A" and r.prompts.requests == []


def test_tool_exposes_no_delete_parameter_or_confirm_flag(tmp_path):
    r = make_rig(tmp_path)
    names = {p["name"] for p in r.registry.get("files").describe()["parameters"]}
    assert not names & {"confirmed", "force", "delete", "overwrite", "recursive", "command"}


@pytest.mark.parametrize("bad_path", ["../x.txt", "a/../../x.txt", "a/./../../x", "C:/x.txt", "a:stream", "sub/..", "con", "nul.txt", "a.txt.",
                                      "a\x00b", "a\nb", "x" * 600, "", "  "])
def test_malformed_and_traversal_paths_are_refused(tmp_path, bad_path):
    r = make_rig(tmp_path, [ONCE] * 2)
    r.bad(action="create", path=bad_path, content="x")
    r.bad(action="read", path=bad_path)
    assert sorted(p.name for p in r.ws.iterdir()) == []


# ---- symlinks ----------------------------------------------------------------------------------------------------------------------------
def test_symlinks_cannot_be_used_to_leave_the_roots(tmp_path):
    if not can_symlink(tmp_path):
        pytest.skip("symlinks cannot be created here (platform proof: CI)")
    r = make_rig(tmp_path, [ONCE] * 8)
    (r.outside / "secret.txt").write_text("OUT", encoding="utf-8")
    (r.ws / "dirlink").symlink_to(r.outside, target_is_directory=True)
    (r.ws / "filelink").symlink_to(r.outside / "secret.txt")
    (r.ws / "dangling").symlink_to(r.outside / "nothing.txt")
    (r.ws / "real.txt").write_text("R", encoding="utf-8")
    r.bad(action="read", path="filelink")
    r.bad(action="read", path="dirlink/secret.txt")
    r.bad(action="list", path="dirlink")
    r.bad(action="write", path="filelink", content="x", expected_sha256=sha("OUT"))
    r.bad(action="create", path="dirlink/new.txt", content="x")
    r.bad(action="create", path="dangling", content="x")
    r.bad(action="move", path="real.txt", destination="dirlink/real.txt")
    r.bad(action="copy", path="filelink", destination="copy.txt")
    r.bad(action="move", path="filelink", destination="moved.txt")
    r.bad(action="create", path="dirlink/../x.txt", content="x")
    assert (r.outside / "secret.txt").read_text(encoding="utf-8") == "OUT"
    assert sorted(p.name for p in r.outside.iterdir()) == ["secret.txt"] and not (r.ws / "copy.txt").exists()
    names = {e["name"]: e for e in r.ok(action="list", path=str(r.ws))["entries"]}
    assert names["dirlink"]["type"] == "link" and names["filelink"]["type"] == "link"       # shown, never followed


def test_symlink_swapped_in_after_the_preview_is_caught(tmp_path):
    if not can_symlink(tmp_path):
        pytest.skip("symlinks cannot be created here (platform proof: CI)")
    r = make_rig(tmp_path)
    (r.ws / "sub").mkdir()
    plan = r.controller.plan("create", path="sub/new.txt", content="x")
    (r.ws / "sub").rmdir()
    (r.ws / "sub").symlink_to(r.outside, target_is_directory=True)
    from jarvis.permissions import PermissionRequest
    req = PermissionRequest(tool=plan.tool, action=plan.action, level=plan.level, resource=plan.resource, resource_type=ResourceType.PATH)
    dec = r.engine.authorize(req)
    if dec.allowed:                              # the engine may already refuse the new resolution: either way nothing is written
        with r.engine.execution_scope(req, dec):
            with pytest.raises(FilesError):
                r.controller.execute(plan)
    assert list(r.outside.iterdir()) == []


# ---- organize --------------------------------------------------------------------------------------------------------------------------
def seed_downloads(r: Rig) -> Path:
    d = r.ws / "dl"
    d.mkdir()
    for n in ("a.jpg", "b.png", "c.pdf", "d.txt", "e.unknown", ".env", "evil.exe"):
        (d / n).write_text(n, encoding="utf-8")
    return d


def test_organize_shows_a_plan_first_and_moves_nothing(tmp_path):
    r = make_rig(tmp_path)
    d = seed_downloads(r)
    plan = r.ok(action="organize", path=str(d))
    assert plan["plan_id"] and plan["executed"] == 0
    froms = {s["from"] for s in plan["steps"]}
    assert froms == {"a.jpg", "b.png", "c.pdf", "d.txt"}                  # unknown types, secrets and executables are skipped, not moved
    assert plan["skipped"]["unmatched"] >= 1 and plan["skipped"]["protected"] >= 2
    assert sorted(p.name for p in d.iterdir()) == sorted(["a.jpg", "b.png", "c.pdf", "d.txt", "e.unknown", ".env", "evil.exe"])
    assert r.prompts.requests == []                                       # the plan is a preview: nothing to confirm yet


def test_organize_custom_rules(tmp_path):
    r = make_rig(tmp_path)
    d = seed_downloads(r)
    plan = r.ok(action="organize", path=str(d), rules=".txt,.unknown=Texte")
    assert {s["to"] for s in plan["steps"]} == {"Texte/d.txt", "Texte/e.unknown"}
    r.bad(action="organize", path=str(d), rules=".txt=../escape")
    r.bad(action="organize", path=str(d), rules=".txt=a/b")
    r.bad(action="organize", path=str(d), rules="*=Alles")


def test_organize_step_moves_exactly_one_file_after_confirmation(tmp_path):
    r = make_rig(tmp_path, [ONCE])
    d = seed_downloads(r)
    plan = r.ok(action="organize", path=str(d))
    step = next(s for s in plan["steps"] if s["from"] == "a.jpg")
    r.ok(action="organize_step", plan_id=plan["plan_id"], step=step["index"])
    assert (d / step["to"].replace("/", os.sep)).read_text(encoding="utf-8") == "a.jpg" and not (d / "a.jpg").exists()
    assert (d / "b.png").exists() and (d / "c.pdf").exists()
    assert len(r.prompts.requests) == 1 and "a.jpg" in " ".join(r.prompts.requests[0].context.values())


def test_organize_every_step_is_asked_even_after_allow_for_session(tmp_path):
    r = make_rig(tmp_path, [SESSION, NO])
    d = seed_downloads(r)
    plan = r.ok(action="organize", path=str(d))
    r.ok(action="organize_step", plan_id=plan["plan_id"], step=0)
    second = plan["steps"][1]
    r.bad(action="organize_step", plan_id=plan["plan_id"], step=1)       # the user said no to the second step
    assert len(r.prompts.requests) == 2                                   # ... because it was asked again
    assert (d / second["from"]).exists() and not (d / second["to"]).exists()


def test_organize_step_cannot_be_replayed_or_forged(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 5)
    d = seed_downloads(r)
    plan = r.ok(action="organize", path=str(d))
    r.ok(action="organize_step", plan_id=plan["plan_id"], step=0)
    r.bad(action="organize_step", plan_id=plan["plan_id"], step=0)                    # replay
    r.bad(action="organize_step", plan_id="0" * 16, step=1)                           # unknown plan
    r.bad(action="organize_step", plan_id=plan["plan_id"], step=99)                   # unknown step
    r.bad(action="organize_step", plan_id=plan["plan_id"], step=-1)
    r.bad(action="organize_step", plan_id=plan["plan_id"], step="x")


def test_organize_step_refused_when_source_changed_or_target_taken(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 4)
    d = seed_downloads(r)
    plan = r.ok(action="organize", path=str(d))
    first, second = plan["steps"][0], plan["steps"][1]
    (d / first["from"]).write_text("jetzt anders und laenger", encoding="utf-8")      # changed after the plan
    r.bad(action="organize_step", plan_id=plan["plan_id"], step=first["index"])
    assert (d / first["from"]).exists()
    (d / Path(second["to"]).parent).mkdir(exist_ok=True)
    (d / second["to"]).write_text("belegt", encoding="utf-8")                       # destination taken meanwhile
    r.bad(action="organize_step", plan_id=plan["plan_id"], step=second["index"])
    assert (d / second["to"]).read_text(encoding="utf-8") == "belegt" and (d / second["from"]).exists()


def test_organize_is_limited_in_size(tmp_path):
    r = make_rig(tmp_path, max_organize_moves=2)
    d = seed_downloads(r)
    plan = r.ok(action="organize", path=str(d))
    assert len(plan["steps"]) == 2 and plan["truncated"] is True


def test_organize_does_not_follow_links(tmp_path):
    if not can_symlink(tmp_path):
        pytest.skip("symlinks cannot be created here (platform proof: CI)")
    r = make_rig(tmp_path, [ONCE] * 3)
    d = r.ws / "dl"
    d.mkdir()
    (r.outside / "x.jpg").write_text("X", encoding="utf-8")
    (d / "x.jpg").symlink_to(r.outside / "x.jpg")
    plan = r.ok(action="organize", path=str(d))
    assert plan["steps"] == []
    (d / "Bilder").symlink_to(r.outside, target_is_directory=True)                  # a rule folder that is a link outside
    (d / "y.jpg").write_text("Y", encoding="utf-8")
    plan = r.ok(action="organize", path=str(d))
    for s in plan["steps"]:
        r.bad(action="organize_step", plan_id=plan["plan_id"], step=s["index"])
    assert sorted(p.name for p in r.outside.iterdir()) == ["x.jpg"]


# ---- emergency stop / budget ---------------------------------------------------------------------------------------------------------
def test_engine_emergency_stop_blocks_every_action(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3)
    (r.ws / "a.txt").write_text("A", encoding="utf-8")
    r.ok(action="read", path="a.txt")
    r.engine.emergency.engage("test", "t")
    r.bad(action="read", path="a.txt")
    r.bad(action="create", path="b.txt", content="x")
    r.bad(action="list", path=str(r.ws))
    assert not (r.ws / "b.txt").exists()


def test_controller_halt_refuses_further_steps_until_resume(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 4)
    (r.ws / "a.txt").write_text("A", encoding="utf-8")
    d = seed_downloads(r)
    plan = r.ok(action="organize", path=str(d))
    r.controller.halt("Notaus")
    assert "halted" in r.bad(action="read", path="a.txt").lower()
    r.bad(action="create", path="b.txt", content="x")
    r.bad(action="organize_step", plan_id=plan["plan_id"], step=0)
    assert not (r.ws / "b.txt").exists() and (d / "a.jpg").exists()
    r.controller.resume()
    r.ok(action="read", path="a.txt")


def test_engine_session_budget_applies(tmp_path):
    r = make_rig(tmp_path, engine_kw={"budget": SessionBudget(2, 600)})
    (r.ws / "a.txt").write_text("A", encoding="utf-8")
    r.ok(action="read", path="a.txt")
    r.ok(action="read", path="a.txt")
    assert "budget" in r.bad(action="read", path="a.txt").lower()


def test_controller_action_budget_and_rate_limit(tmp_path):
    r = make_rig(tmp_path, max_actions_per_session=2)
    (r.ws / "a.txt").write_text("A", encoding="utf-8")
    r.ok(action="read", path="a.txt")
    r.ok(action="read", path="a.txt")
    assert "budget" in r.bad(action="read", path="a.txt").lower()
    r2 = make_rig(tmp_path / "second", max_actions_per_minute=1)
    (r2.ws / "a.txt").write_text("A", encoding="utf-8")
    r2.ok(action="read", path="a.txt")
    assert "per minute" in r2.bad(action="read", path="a.txt").lower()


def test_preview_is_short_and_audit_holds_no_file_contents(tmp_path):
    r = make_rig(tmp_path, [ONCE])
    r.ok(action="create", path="a.txt", content="".join(f"Zeile-{i}-vertraulich\n" for i in range(1, 7)))
    shown = "\n".join(q.to_text() + str(dict(q.context)) for q in r.prompts.requests)
    assert "Zeile-1-vertraulich" in shown and "Zeile-3-vertraulich" in shown and "Zeile-4-vertraulich" not in shown     # a preview, not the file
    audit = "\n".join(str(e.to_dict()) for e in r.sink.events)
    assert "vertraulich" not in audit and audit


# ---- bootstrap wiring ---------------------------------------------------------------------------------------------------------------------
def _core(tmp_path, **env):
    from jarvis.bootstrap import build_core
    from jarvis.config import load_settings
    base = {"JARVIS_WORKSPACE": str(tmp_path / "workspace"), "JARVIS_LOG_DIR": str(tmp_path / "logs"), "JARVIS_MODE": "development"}
    (tmp_path / "workspace").mkdir(exist_ok=True)
    return build_core(load_settings(env={**base, **env}))


def test_core_has_files_subsystem_off_by_default(tmp_path):
    core = _core(tmp_path)
    assert core.subsystems["files"].status == "disabled" and "files" not in core.tools


def test_core_enabled_files_is_halted_by_the_central_emergency_stop(tmp_path):
    core = _core(tmp_path, JARVIS_FILES_ENABLED="true")
    sub = core.subsystems["files"]
    assert sub.status == "enabled" and "files" in core.tools
    report = core.permissions.emergency.trigger("test", "t")
    assert {c.name: c.outcome.value for c in report.components}["files"] == "stopped"
    assert sub.controller.halted and sub.describe()["status"] == "halted"
    assert core.tools.execute("files", action="list").success is False


def test_name_lists_do_not_fall_behind_the_coding_agent():
    from jarvis.coding import policy as cp
    from jarvis.files import names as fn
    assert fn.SECRET_NAMES >= cp.SECRET_NAMES and set(fn.SECRET_PATTERNS) >= set(cp.SECRET_PATTERNS) and fn.SECRET_DIRS >= cp.SECRET_DIRS
    assert fn.BLOCKED_EXTENSIONS >= cp.BLOCKED_WRITE_EXTENSIONS and fn.RESERVED >= cp.RESERVED and set(fn.EXAMPLE_SUFFIXES) >= set(cp.EXAMPLE_SUFFIXES)
