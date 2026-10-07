"""Coding tool + PermissionEngine + CodingController, with the fake provider (no disk, no processes)."""
import hashlib
import os
import re

import pytest

from coding_util import CALC, G, NO, ONCE, PYPROJECT, R, SESSION, TEST_CALC, Y, make_rig, seed
from jarvis.coding.models import CommandResult
from jarvis.llm.base import LLMProvider, LLMResponse
from jarvis.permissions import DecisionStatus


@pytest.fixture
def rig(tmp_path):
    return make_rig(tmp_path, [ONCE] * 80)


@pytest.fixture
def started(rig):
    rig.start()
    return rig


def code(out):
    assert not out.success
    if isinstance(out.output, dict):
        return out.output["code"]
    m = re.search(r"\[([a-z_]+)\]", out.error or "")
    return m.group(1) if m else None


def level(out):
    return out.permission.level


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def after_confirmation(rig, fn):
    orig = rig.prompts.confirm

    def hook(request):
        choice = orig(request)
        fn()
        return choice

    rig.prompts.confirm = hook


# ---- levels, sessions ---------------------------------------------------------------------------------------------------------------
def test_status_is_green_and_needs_no_session(tmp_path):
    r = make_rig(tmp_path, [])
    out = r.run(action="status")
    assert out.success and level(out) is G and out.output["session"] is None and r.prompts.requests == []


def test_start_is_yellow_asked_and_describes_what_it_opens(tmp_path):
    r = make_rig(tmp_path, [ONCE])
    out = r.run(action="start", workspace=str(r.project))
    assert out.success and level(out) is Y and out.output["status"] == "active" and out.output["project"]["language"] == "Python"
    text = r.prompts.requests[0].to_text()
    assert str(r.project) in text and "Python" in text and "pytest" in text and "Tests führen Projektcode aus" in text


def test_declined_start_opens_nothing(tmp_path):
    r = make_rig(tmp_path, [NO])
    assert not r.run(action="start", workspace=str(r.project)).success
    assert r.ok(action="status")["session"] is None


def test_actions_need_a_session(rig):
    for kw in ({"action": "info"}, {"action": "list"}, {"action": "read", "path": "calc.py"}, {"action": "write", "path": "a.py", "content": "x"},
               {"action": "test"}, {"action": "stop"}, {"action": "changes"}):
        assert code(rig.run(**kw)) == "not_started", kw


def test_start_twice_and_invalid_workspaces(started):
    assert code(started.run(action="start", workspace=str(started.project))) == "already_started"


@pytest.mark.parametrize("where", ["/", "..", "../..", "C:\\Windows", "\\\\server\\share\\x", "/etc", "/tmp"])
def test_workspaces_outside_the_configured_roots_are_red(tmp_path, where):
    r = make_rig(tmp_path, [ONCE])
    out = r.run(action="start", workspace=where)
    assert not out.success and r.ok(action="status")["session"] is None
    assert (out.permission is not None and level(out) is R) or code(out) in ("invalid_input",)


def test_the_root_itself_may_be_a_workspace_but_not_its_parent(tmp_path):
    r = make_rig(tmp_path, [ONCE])
    assert level(r.run(action="start", workspace=str(r.ws.parent))) is R
    assert r.run(action="start", workspace=str(r.ws)).success


def test_relative_workspace_names_are_resolved_inside_the_root(tmp_path):
    r = make_rig(tmp_path, [ONCE])
    assert r.run(action="start", workspace="proj").success
    r2 = make_rig(tmp_path / "x", [ONCE])
    assert level(r2.run(action="start", workspace="../escape")) is R


def test_session_overview_and_stop(started):
    o = started.ok(action="status")
    assert o["session"]["status"] == "active" and o["session"]["is_jarvis_workspace"] is False and o["session"]["actions"] >= 0
    out = started.ok(action="stop")
    assert out["stopped"] == o["session"]["id"]
    assert started.ok(action="status")["session"]["status"] == "completed"
    assert code(started.run(action="read", path="calc.py")) == "not_started"
    started.start()  # a new session is possible and has a new identity
    assert started.ok(action="status")["session"]["id"] != o["session"]["id"]


# ---- reading --------------------------------------------------------------------------------------------------------------------------
def test_reading_and_listing_are_green_and_silent(started):
    n = len(started.prompts.requests)
    for kw in ({"action": "info"}, {"action": "list"}, {"action": "list", "path": "tests"}, {"action": "read", "path": "calc.py"},
               {"action": "search", "pattern": "return"}, {"action": "changes"}):
        out = started.run(**kw)
        assert out.success and level(out) is G, kw
    assert len(started.prompts.requests) == n


def test_read_returns_content_hash_and_line_window(started):
    out = started.ok(action="read", path="calc.py")
    assert out["content"] == CALC.rstrip("\n") and out["sha256"] == sha(CALC) and out["lines"] == 6
    part = started.ok(action="read", path="calc.py", offset=5, limit=2)
    assert part["content"].startswith("def mul") and part["from_line"] == 5 and part["to_line"] == 6
    assert code(started.run(action="read", path="missing.py")) == "file_not_found"
    assert code(started.run(action="read", path="tests")) == "invalid_input"
    assert code(started.run(action="read", path="calc.py", limit=0)) == "invalid_input"


def test_secrets_inside_files_are_never_returned(tmp_path):
    secret = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"
    r = make_rig(tmp_path, [ONCE] * 5, files={"pyproject.toml": PYPROJECT, "cfg.py": f'API_KEY = "{secret}"\nNAME = "x"\n'})
    r.start()
    out = r.ok(action="read", path="cfg.py")
    assert secret not in str(out) and out["secrets_redacted"] is True and 'NAME = "x"' in out["content"]
    assert secret not in str(r.ok(action="search", pattern="API_KEY")) and secret not in r.audit_blob()


@pytest.mark.parametrize("name", [".env", ".ENV", ".env.local", "prod.env", "key.pem", "server.KEY", "id_rsa", "Id_Rsa", "id_ed25519.pub", "credentials.json",
                                  "Credentials", ".npmrc", ".netrc", "secrets.yaml", "store.kdbx", ".aws/credentials", ".ssh/config", "a/b/.env", ".git/config",
                                  ".git/HEAD", "sub/.git/hooks/pre-commit"])
def test_secret_and_protected_files_are_red_for_every_operation(tmp_path, name):
    r = make_rig(tmp_path, [ONCE] * 10, files={"pyproject.toml": PYPROJECT, name: "SECRET=hunter22"})
    r.start()
    for kw in ({"action": "read", "path": name}, {"action": "write", "path": name, "mode": "create", "content": "x"},
               {"action": "delete", "path": name}, {"action": "list", "path": name}):
        out = r.run(**kw)
        assert not out.success and level(out) is R and out.permission.status is DecisionStatus.DENIED, (name, kw)
    assert r.provider.calls_named("read_file") == [] or all("hunter22" not in str(c) for c in r.provider.calls_named("read_file"))
    assert r.provider.files[os.path.join(str(r.project), *name.split("/"))] == b"SECRET=hunter22"


def test_example_env_files_are_ordinary_files(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3, files={"pyproject.toml": PYPROJECT, ".env.example": "KEY=changeme\n"})
    r.start()
    assert r.ok(action="read", path=".env.example")["content"].startswith("KEY=")


def test_list_marks_protected_names_and_skips_noise_directories(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3, files={"pyproject.toml": PYPROJECT, ".env": "A=1", "src/m.py": "x=1", "node_modules/x/i.js": "1", ".git/HEAD": "ref"})
    r.start()
    out = r.ok(action="list", recursive=True)
    paths = {e["path"]: e for e in out["entries"]}
    assert paths[".env"]["protected"] == "secret" and "src/m.py" in paths and paths["node_modules"].get("skipped") and paths[".git"].get("skipped")
    assert not any(p.startswith(("node_modules/", ".git/")) for p in paths)
    assert len(r.ok(action="list", recursive=True, limit=2)["entries"]) == 2


def test_search_finds_literal_text_with_filters_and_limits(tmp_path):
    files = {"pyproject.toml": PYPROJECT, "a.py": "x = 1\nNeedle here\n", "b.txt": "needle in txt\n", "bin.dat": "needle\x00\x01", "big.py": "needle " * 50,
             ".env": "needle=1", "node_modules/m.js": "needle"}
    r = make_rig(tmp_path, [ONCE] * 8, files=files, max_file_size=200, max_search_results=3)
    r.start()
    out = r.ok(action="search", pattern="needle", ignore_case=True)
    assert {h["path"] for h in out["hits"]} == {"a.py", "b.txt"} and out["skipped"]["binary"] == 1 and out["skipped"]["secret_files"] == 1
    assert out["skipped"]["too_large"] == 1
    assert {h["path"] for h in r.ok(action="search", pattern="needle", ignore_case=True, glob="*.py")["hits"]} == {"a.py"}
    assert r.ok(action="search", pattern="Needle")["hits"][0]["line"] == 2  # case-sensitive by default
    assert r.ok(action="search", pattern="e", ignore_case=True)["truncated"] is True
    for bad in ("", "   ", "x" * 300):
        assert code(r.run(action="search", pattern=bad)) == "invalid_input"
    assert code(r.run(action="search", pattern="x", glob="../*.py")) == "invalid_input"


def test_search_never_leaves_the_workspace_or_follows_links(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 5, files={"pyproject.toml": PYPROJECT, "a.py": "x"})
    outside = r.ws.parent / "outside"
    r.provider.put(str(outside / "o.py"), "needle outside")
    r.provider.symlinks[str(r.project / "link")] = str(outside)
    r.start()
    out = r.ok(action="search", pattern="needle")
    assert out["hits"] == [] and out["skipped"]["links"] == 1
    assert code(r.run(action="search", pattern="needle", path="link")) in ("path_denied",)
    assert code(r.run(action="search", pattern="needle", path="../outside")) == "path_denied"


# ---- writing --------------------------------------------------------------------------------------------------------------------------
def test_replace_asks_shows_a_summary_and_writes(started):
    old = CALC
    out = started.run(action="write", path="calc.py", mode="replace", old_text="return a - b", new_text="return a + b")
    assert out.success and level(out) is Y
    assert started.provider.text(str(started.file("calc.py"))) == old.replace("a - b", "a + b")
    text = started.prompts.requests[-1].to_text()
    assert "calc.py" in text and "+1 / -1 Zeilen" in text and "return a + b" in text and "return a - b" in text
    assert out.output["added_lines"] == 1 and out.output["removed_lines"] == 1 and out.output["old_sha256"] == sha(old)


def test_create_overwrite_and_new_subdirectories(started):
    assert started.run(action="write", path="pkg/new.py", content="def foo():\n    return 1\n").success
    assert started.provider.text(str(started.file("pkg/new.py"))) == "def foo():\n    return 1\n"
    assert "Funktion foo()" in started.prompts.requests[-1].to_text() and "neue Datei" in started.prompts.requests[-1].to_text()
    cur = started.ok(action="read", path="pkg/new.py")["sha256"]
    out = started.run(action="write", path="pkg/new.py", mode="overwrite", content="X = 2\n", expected_sha256=cur)
    assert out.success and started.provider.text(str(started.file("pkg/new.py"))) == "X = 2\n"


def test_write_validation(started):
    assert code(started.run(action="write", path="calc.py", mode="create", content="x")) == "file_exists"
    assert code(started.run(action="write", path="calc.py", mode="overwrite", content="x")) == "invalid_input"          # needs the hash
    assert code(started.run(action="write", path="calc.py", mode="overwrite", content="x", expected_sha256="0" * 64)) == "file_changed"
    assert code(started.run(action="write", path="calc.py", mode="overwrite", content="x", expected_sha256="zz")) == "invalid_input"
    assert code(started.run(action="write", path="calc.py", mode="replace", old_text="nonsense", new_text="x")) == "invalid_input"
    assert code(started.run(action="write", path="calc.py", mode="replace", old_text="return", new_text="x")) == "invalid_input"   # not unique
    assert code(started.run(action="write", path="calc.py", mode="replace", old_text="", new_text="x")) == "invalid_input"
    assert code(started.run(action="write", path="calc.py", mode="bogus", content="x")) == "invalid_input"
    assert code(started.run(action="write", path="new.py", mode="create")) == "invalid_input"
    assert code(started.run(action="write", path="nope.py", mode="replace", old_text="a", new_text="b")) == "file_not_found"
    assert code(started.run(action="write", path="n.py", mode="create", content="a\x00b")) == "binary_file"
    assert code(started.run(action="write", path="n.py", mode="create", content=5)) == "invalid_input"
    assert started.provider.calls_named("write_file") == []


def test_size_limit(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 4, max_file_size=100)
    r.start()
    assert code(r.run(action="write", path="big.py", mode="create", content="x" * 101)) == "file_too_large"
    r.provider.put(str(r.project / "huge.txt"), "y" * 500)
    assert code(r.run(action="read", path="huge.txt")) == "file_too_large"
    assert code(r.run(action="write", path="huge.txt", mode="replace", old_text="y", new_text="z")) == "file_too_large"


@pytest.mark.parametrize("name", ["tool.exe", "x.dll", "a.msi", "L.LNK", "m.pyc", "lib.so", "x.jar", "d.bin"])
def test_binary_and_executable_file_types_are_red(started, name):
    out = started.run(action="write", path=name, mode="create", content="x")
    assert level(out) is R and not out.success and started.provider.calls_named("write_file") == []


def test_a_write_that_would_introduce_a_secret_is_red_and_not_echoed(started):
    for text in ('KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"\n', "password = hunter22abc\n", "-----BEGIN RSA PRIVATE KEY-----\n", "AKIAABCDEFGHIJKLMNOP\n"):
        out = started.run(action="write", path="s.py", mode="create", content=text)
        assert level(out) is R and "secret_detected" in out.permission.reason and not out.success
    assert "sk-ant" not in started.prompt_blob() and "sk-ant" not in started.audit_blob() and "hunter22abc" not in started.audit_blob()
    assert started.provider.calls_named("write_file") == []


def test_existing_secrets_are_neither_rewritten_nor_leaked(tmp_path):
    secret = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"
    r = make_rig(tmp_path, [ONCE] * 5, files={"pyproject.toml": PYPROJECT, "cfg.py": f'KEY = "{secret}"\nNAME = "a"\n'})
    r.start()
    h = sha(f'KEY = "{secret}"\nNAME = "a"\n')
    out = r.run(action="write", path="cfg.py", mode="overwrite", content="x", expected_sha256=h)
    assert level(out) is R and "mode=replace" in out.permission.reason
    assert r.run(action="write", path="cfg.py", mode="replace", old_text='NAME = "a"', new_text='NAME = "b"').success  # the secret is untouched
    assert secret in r.provider.text(str(r.file("cfg.py"))) and secret not in r.prompt_blob() and secret not in r.audit_blob()


def test_crlf_files_keep_their_line_endings_on_replace(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 4, files={"pyproject.toml": PYPROJECT, "w.txt": "one\r\ntwo\r\nthree\r\n"})
    r.start()
    assert r.run(action="write", path="w.txt", mode="replace", old_text="two\nthree", new_text="2\n3").success
    assert r.provider.files[str(r.file("w.txt"))] == b"one\r\n2\r\n3\r\n"


def test_writes_use_exact_resource_bound_grants(tmp_path):
    r = make_rig(tmp_path, [ONCE, ONCE, SESSION, ONCE])
    r.start()
    first = r.run(action="write", path="a.py", mode="create", content="a = 1\n")
    assert first.permission.resolved_resource == str(r.file("a.py"))
    second = r.run(action="write", path="b.py", mode="create", content="b = 1\n")  # session grant for b.py only
    assert second.success and second.permission.scope.value == "session"
    n = len(r.prompts.requests)
    r.ok(action="write", path="b.py", mode="replace", old_text="b = 1", new_text="b = 2")
    assert len(r.prompts.requests) == n  # same file: covered
    assert r.run(action="write", path="c.py", mode="create", content="c = 1\n").success and len(r.prompts.requests) == n + 1  # other file: asked again


def test_dependency_files_are_always_asked_individually(tmp_path):
    r = make_rig(tmp_path, [ONCE, SESSION, SESSION])
    r.start()
    for old, new in (("0.1", "0.2"), ("0.2", "0.3")):
        out = r.run(action="write", path="pyproject.toml", mode="replace", old_text=f'version = "{old}"', new_text=f'version = "{new}"')
        assert out.success and out.permission.scope.value == "once"  # a session answer is not honoured
    assert [q.action for q in r.prompts.requests][-2:] == ["write.deps", "write.deps"]


def test_a_stale_file_is_never_overwritten(started):
    path = str(started.file("calc.py"))
    h = started.ok(action="read", path="calc.py")["sha256"]
    after_confirmation(started, lambda: started.provider.put(path, "# someone else changed this\n"))
    out = started.run(action="write", path="calc.py", mode="overwrite", content="mine\n", expected_sha256=h)
    assert not out.success and code(out) in ("file_changed", "not_authorized", "target_changed")
    assert started.provider.text(path) == "# someone else changed this\n"


def test_race_between_the_final_check_and_the_write_is_caught_by_the_provider(started):
    path = str(started.file("calc.py"))
    started.provider.writes_blocked_by_race[path] = b"# race\n"
    out = started.run(action="write", path="calc.py", mode="replace", old_text="return a - b", new_text="return a + b")
    assert code(out) == "file_changed" and started.provider.text(path) == "# race\n"
    assert started.ok(action="changes")["changes"] == []  # nothing was recorded as done


def test_symlinks_are_never_written_through(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 6)
    r.provider.put(str(r.ws / "other" / "t.py"), "t = 1\n")
    r.provider.symlinks[str(r.project / "ln.py")] = str(r.ws / "other" / "t.py")
    r.provider.symlinks[str(r.project / "dirlink")] = str(r.ws / "other")
    r.start()
    assert code(r.run(action="write", path="ln.py", mode="replace", old_text="t", new_text="u")) == "path_denied"
    assert code(r.run(action="write", path="dirlink/t.py", mode="replace", old_text="t", new_text="u")) == "path_denied"  # outside the workspace
    assert code(r.run(action="delete", path="ln.py")) == "path_denied"
    assert r.provider.text(str(r.ws / "other" / "t.py")) == "t = 1\n"
    # a link that stays INSIDE the workspace may be read through, but never written or deleted through
    r.provider.put(str(r.project / "src" / "inside.py"), "i = 1\n")
    r.provider.symlinks[str(r.project / "alias")] = str(r.project / "src")
    assert r.run(action="read", path="alias/inside.py").success
    assert code(r.run(action="write", path="alias/inside.py", mode="replace", old_text="1", new_text="2")) == "path_denied"
    assert code(r.run(action="write", path="alias/new.py", mode="create", content="n = 1\n")) == "path_denied"
    assert code(r.run(action="delete", path="alias/inside.py")) == "path_denied"
    assert r.provider.text(str(r.project / "src" / "inside.py")) == "i = 1\n"


# ---- delete -----------------------------------------------------------------------------------------------------------------------------
def test_delete_is_always_asked_even_if_a_session_grant_is_offered(tmp_path):
    r = make_rig(tmp_path, [ONCE, SESSION, SESSION], files={"pyproject.toml": PYPROJECT, "a.py": "1\n", "b.py": "2\n"})
    r.start()
    for name in ("a.py", "b.py"):
        out = r.run(action="delete", path=name)
        assert out.success and out.permission.scope.value == "once" and level(out) is Y
    dels = [q for q in r.prompts.requests if q.action == "delete"]
    assert len(dels) == 2 and not any(q.session_allowed for q in dels)
    assert str(r.file("a.py")) not in r.provider.files


def test_delete_refuses_directories_missing_and_changed_files(started):
    assert code(started.run(action="delete", path="tests")) == "invalid_input"
    assert code(started.run(action="delete", path="ghost.py")) == "file_not_found"
    assert code(started.run(action="delete", path="calc.py", expected_sha256="1" * 64)) == "file_changed"
    path = str(started.file("calc.py"))
    after_confirmation(started, lambda: started.provider.put(path, "changed\n"))
    out = started.run(action="delete", path="calc.py")
    assert not out.success and path in started.provider.files and started.provider.text(path) == "changed\n"


def test_changes_are_tracked_and_merged(started):
    started.ok(action="write", path="n.py", mode="create", content="a = 1\n")
    started.ok(action="write", path="n.py", mode="replace", old_text="a = 1", new_text="a = 2")
    started.ok(action="write", path="calc.py", mode="replace", old_text="return a - b", new_text="return a + b")
    started.ok(action="delete", path="tests/test_calc.py")
    ch = started.ok(action="changes")["changes"]
    assert set(ch) == {"n.py: create +2/-0", "calc.py: modify +1/-1", f"tests/test_calc.py: delete +0/-{len(TEST_CALC.splitlines())}"} or len(ch) == 3
    started.ok(action="write", path="tmp.py", mode="create", content="x\n")
    started.ok(action="delete", path="tmp.py")
    assert not any(c.startswith("tmp.py") for c in started.ok(action="changes")["changes"])  # created and deleted again: no net change
    assert started.ok(action="status")["session"]["changed_files"] == ["calc.py", "n.py", "tests/test_calc.py"]


# ---- JARVIS repository ----------------------------------------------------------------------------------------------------------------------
JARVIS_FILES = {"pyproject.toml": '[project]\nname = "jarvis-ai"\nversion = "0.1.0"\n', "src/jarvis/__init__.py": "__version__ = '0'\n",
                "src/jarvis/core.py": "x = 1\n", "src/jarvis/permissions/engine.py": "e = 1\n", "tests/test_x.py": "def test_x():\n    assert True\n"}


def test_the_jarvis_repository_is_recognised_and_every_change_is_asked_individually(tmp_path):
    r = make_rig(tmp_path, [ONCE, SESSION, SESSION, ONCE, ONCE], files=JARVIS_FILES)
    out = r.ok(action="start", workspace=str(r.project))
    assert out["project"]["is_jarvis_workspace"] is True and "strenge Regeln" in r.prompts.requests[0].to_text()
    assert r.ok(action="status")["session"]["is_jarvis_workspace"] is True
    # reading / analysing / searching: free
    assert r.run(action="read", path="src/jarvis/core.py").success and r.run(action="search", pattern="e = 1").success
    for new in ("x = 2", "x = 3"):
        out = r.run(action="write", path="src/jarvis/core.py", mode="replace", old_text=new[:-1] + str(int(new[-1]) - 1), new_text=new)
        assert out.success and out.permission.scope.value == "once"      # a session answer is never honoured here
    assert [q.action for q in r.prompts.requests if q.action.startswith("write")] == ["write.jarvis", "write.jarvis"]
    assert all("jarvis-repository" in q.to_text() or "JARVIS" in q.to_text() for q in r.prompts.requests if q.action.startswith("write"))
    d = r.run(action="delete", path="src/jarvis/core.py")
    assert d.success and r.prompts.requests[-1].action == "delete.jarvis"


def test_jarvis_repository_tests_run_after_confirmation_like_any_other(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 4, files=JARVIS_FILES)
    r.start()
    out = r.run(action="test")
    assert out.success and level(out) is Y and r.provider.commands


def test_jarvis_repository_secret_and_git_rules_still_apply(tmp_path):
    files = {**JARVIS_FILES, ".env": "K=1"}
    r = make_rig(tmp_path, [ONCE] * 6, files=files)
    r.start()
    assert level(r.run(action="write", path=".env", mode="replace", old_text="K", new_text="L")) is R
    assert level(r.run(action="git", sub="push")) is R


# ---- tests --------------------------------------------------------------------------------------------------------------------------------------
def test_test_runs_a_structured_command_and_reports_the_result(started):
    started.provider.command_handler = lambda spec: CommandResult(
        1, "FAILED tests/test_calc.py::test_add - assert -1 == 5\n=== 1 failed, 1 passed in 0.03s ===\n", "", False, False, 0.03)
    out = started.run(action="test")
    assert out.success and level(out) is Y and out.output["passed"] is False and out.output["exit_code"] == 1
    assert out.output["summary"] == "1 failed, 1 passed" and out.output["failures"] == ["tests/test_calc.py::test_add"]
    spec = started.provider.commands[-1]
    assert isinstance(spec.argv, tuple) and spec.argv[1:3] == ("-m", "pytest") and spec.cwd == str(started.project) and spec.timeout == 120
    assert spec.argv[0] == __import__("sys").executable and "-p" in spec.argv and "no:cacheprovider" in spec.argv
    assert started.ok(action="status")["session"]["tests_run"] == 1


def test_test_prompt_names_runner_directory_and_changed_files(started):
    started.ok(action="write", path="calc.py", mode="replace", old_text="a - b", new_text="a + b")
    started.run(action="test", runner="python -m unittest", args=["-v"])
    t = started.prompts.requests[-1].to_text()
    assert "python -m unittest -v" in t and str(started.project) in t and "calc.py" in t and "Shell" in t


def test_a_test_approval_covers_exactly_one_state_of_the_code(tmp_path):
    r = make_rig(tmp_path, [ONCE, SESSION, SESSION, SESSION, SESSION])
    r.start()
    first = r.run(action="test")                       # answered: session
    assert first.permission.scope.value == "session"
    n = len(r.prompts.requests)
    assert r.run(action="test").success and len(r.prompts.requests) == n   # same code state: no new question
    r.ok(action="write", path="calc.py", mode="replace", old_text="a - b", new_text="a + b")
    m = len(r.prompts.requests)
    assert r.run(action="test").success and len(r.prompts.requests) == m + 1  # the code changed: asked again


def test_runner_and_argument_validation(started):
    assert code(started.run(action="test", runner="make test")) == "command_not_allowed"
    assert code(started.run(action="test", runner="npm test", args=["--silent"])) == "command_not_allowed"
    assert code(started.run(action="test", runner="python -m pytest", args=["-p", "evil"])) == "command_not_allowed"
    assert code(started.run(action="test", args="--rootdir=/")) == "command_not_allowed"
    assert code(started.run(action="test", args=["../../etc"])) == "path_denied"
    assert code(started.run(action="test", args=["C:\\Windows"])) in ("path_denied", "command_not_allowed")
    assert code(started.run(action="test", args=["a;b"])) == "command_not_allowed"
    assert code(started.run(action="test", args="x " * 20)) == "invalid_input"
    assert started.provider.commands == []
    assert started.run(action="test", args=["tests/test_calc.py::test_add", "-x", "-k", "add or mul", "--tb=short"]).success


def test_test_output_is_redacted_and_marked_untrusted(started):
    secret = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"
    started.provider.command_handler = lambda spec: CommandResult(1, f"token={secret} leaked\n1 failed in 0.1s\n", f"password=hunter22abc", False, False, 0.1)
    out = started.ok(action="test")
    assert secret not in str(out) and "hunter22abc" not in str(out) and out["secrets_redacted"] is True and "untrusted_content" in out
    assert secret not in started.audit_blob()


def test_timeouts_and_flooding_are_reported(started):
    started.provider.command_handler = lambda spec: CommandResult(None, "partial", "", True, False, 120.0)
    out = started.ok(action="test")
    assert out["timed_out"] is True and out["passed"] is False and out["exit_code"] is None
    started.provider.command_handler = lambda spec: CommandResult(0, "x" * 10, "", False, True, 1.0)
    out = started.ok(action="test")
    assert out["output_truncated"] is True and out["passed"] is False


def test_npm_test_is_refused_where_it_would_need_a_command_interpreter(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 4, files={"package.json": '{"scripts": {"test": "jest"}, "devDependencies": {"jest": "1"}}'},
                 test_commands=("npm test", "pytest"))
    r.provider.executables["npm"] = "C:\\Program Files\\nodejs\\npm.cmd"
    r.start()
    assert r.ok(action="info")["default_runner"] == "npm test"
    assert code(r.run(action="test")) == "runner_unavailable"
    r.provider.executables["npm"] = "/usr/bin/npm"
    assert r.run(action="test").success and r.provider.commands[-1].argv == ("/usr/bin/npm", "test")


def test_disabled_runners_are_not_available(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3, test_commands=("pytest",))
    r.start()
    assert code(r.run(action="test", runner="python -m unittest")) == "command_not_allowed"
    assert r.run(action="test", runner="pytest").success


# ---- git -----------------------------------------------------------------------------------------------------------------------------------------
def test_git_reads_are_green_hardened_and_filtered(started):
    started.provider.command_handler = lambda spec: CommandResult(0, " M calc.py\n", "", False, False, 0.01)
    for sub in ("status", "diff", "log"):
        out = started.run(action="git", sub=sub)
        assert out.success and level(out) is G, sub
        argv = started.provider.commands[-1].argv
        assert argv[0] == "/usr/bin/git" and "--no-pager" in argv and "core.fsmonitor=false" in argv and sub in argv
        assert started.provider.commands[-1].env_profile == "git"
    diff = started.provider.commands[-2].argv
    assert "--no-ext-diff" in diff and "--no-textconv" in diff and ":(exclude,glob)**/.env" in diff and "--" in diff
    assert not any(a in started.provider.commands[-1].argv for a in ("push", "commit", "--hard"))


@pytest.mark.parametrize("sub", ["commit", "push", "reset", "clean", "checkout", "rebase", "merge", "pull", "fetch", "stash", "config", "gc", "rm", "add",
                                 "reset --hard", "push --force", "diff;rm", "-c", "", None])
def test_every_other_git_operation_is_a_red_audited_refusal(started, sub):
    out = started.run(action="git", sub=sub)
    assert not out.success and level(out) is R and out.permission.status is DecisionStatus.DENIED
    assert started.provider.commands == []
    assert any(e.type.value == "permission_denied" for e in started.sink.events)


def test_git_output_secrets_are_redacted_and_no_git_means_a_clear_error(started):
    started.provider.command_handler = lambda spec: CommandResult(0, "+API_KEY = 'sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123'\n", "", False, False, 0.0)
    out = started.ok(action="git", sub="diff")
    assert "sk-ant" not in out["output"] and out["secrets_redacted"] is True
    started.provider.executables.pop("git")
    assert code(started.run(action="git", sub="status")) == "runner_unavailable"


# ---- guards: sessions, workspace, budget, halt -------------------------------------------------------------------------------------------------------
def test_wrong_and_old_sessions_are_rejected(started):
    sid = started.ok(action="status")["session"]["id"]
    assert code(started.run(action="read", path="calc.py", session="c99-xxxx")) == "session_mismatch"
    assert started.run(action="read", path="calc.py", session=sid).success
    started.ok(action="stop")
    started.start()
    assert code(started.run(action="read", path="calc.py", session=sid)) == "session_mismatch"


def test_a_removed_or_replaced_workspace_fails_the_session(started):
    started.provider.dirs.discard(str(started.project))
    for k in [k for k in started.provider.files if k.startswith(str(started.project))]:
        del started.provider.files[k]
    out = started.run(action="read", path="calc.py")
    assert code(out) == "workspace_changed" and started.ok(action="status")["session"]["status"] == "failed"
    assert code(started.run(action="info")) in ("session_ended", "workspace_changed")


def test_a_workspace_swapped_for_a_link_fails(started):
    started.provider.dirs.discard(str(started.project))
    started.provider.symlinks[str(started.project)] = str(started.ws.parent)
    assert code(started.run(action="list")) == "workspace_changed"


def test_workspace_swapped_between_confirmation_and_write(tmp_path):
    r = make_rig(tmp_path, [ONCE, ONCE])
    r.start()
    after_confirmation(r, lambda: r.provider.symlinks.__setitem__(str(r.project / "calc.py"), str(r.ws.parent / "evil.py")))
    out = r.run(action="write", path="calc.py", mode="replace", old_text="a - b", new_text="a + b")
    assert not out.success and r.provider.calls_named("write_file") == []


def test_action_budget_ends_the_session(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 5, max_actions_per_session=4, max_actions_per_minute=0)
    r.start()
    for _ in range(4):
        assert r.run(action="read", path="calc.py").success
    out = r.run(action="read", path="calc.py")
    assert code(out) == "action_budget_exceeded" and r.ok(action="status")["session"]["status"] == "failed"
    assert code(r.run(action="list")) == "action_budget_exceeded"
    assert r.run(action="stop").success  # the user side can always end it
    r.start()
    assert r.run(action="read", path="calc.py").success  # a new (confirmed) session has a fresh budget


def test_rate_limit(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3, max_actions_per_minute=2, max_actions_per_session=0)
    r.start()
    assert r.run(action="read", path="calc.py").success and r.run(action="read", path="calc.py").success
    assert code(r.run(action="read", path="calc.py")) == "rate_limited"


def test_halt_resume_stop(started):
    started.controller.halt("user")
    assert started.ok(action="status")["session"]["status"] == "halted"
    for kw in ({"action": "read", "path": "calc.py"}, {"action": "list"}, {"action": "write", "path": "z.py", "content": "z"}, {"action": "test"}):
        assert code(started.run(**kw)) == "failsafe", kw
    assert started.provider.calls_named("write_file") == [] and started.provider.commands == []
    started.controller.resume()
    assert started.ok(action="status")["session"]["status"] == "active" and started.run(action="read", path="calc.py").success
    started.controller.halt("again")
    assert started.controller.stop() is True and started.ok(action="status")["session"]["status"] == "completed"


def test_halt_and_resume_are_not_tool_actions(started):
    for a in ("halt", "resume", "kill", "unlock"):
        assert code(started.run(action=a)) == "invalid_input"
    started.controller.halt()
    assert code(started.run(action="resume")) == "invalid_input" and started.controller.halted is not None


def test_halt_during_confirmation_stops_the_action(tmp_path):
    r = make_rig(tmp_path, [ONCE, ONCE])
    r.start()
    after_confirmation(r, lambda: r.controller.halt("user pressed stop"))
    out = r.run(action="write", path="a.py", mode="create", content="a = 1\n")
    assert not out.success and code(out) == "failsafe" and str(r.file("a.py")) not in r.provider.files


# ---- LLM-assisted plan ------------------------------------------------------------------------------------------------------------------------------
class Recorder(LLMProvider):
    name = "recorder"

    def __init__(self, reply="1. change calc.py\n2. run tests", fail=False):
        self.requests, self.reply, self.fail = [], reply, fail

    def complete(self, request):
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("api failed token=abc123456789")
        return LLMResponse(self.reply)


def test_plan_needs_a_connected_llm(started):
    assert code(started.run(action="plan", goal="fix it")) == "llm_unavailable"


def test_plan_asks_always_shows_exactly_what_is_sent_and_redacts(tmp_path):
    secret = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"
    llm = Recorder()
    r = make_rig(tmp_path, [ONCE, SESSION, SESSION], llm=llm,
                 files={"pyproject.toml": PYPROJECT, "calc.py": CALC + f'KEY = "{secret}"\n', ".env": "A=1", "tests/test_calc.py": TEST_CALC})
    r.start()
    out = r.run(action="plan", goal="make add() correct", paths="calc.py,tests/test_calc.py")
    assert out.success and level(out) is Y and "change calc.py" in out.output["plan"]
    q = r.prompts.requests[-1]
    assert not q.session_allowed and "calc.py" in q.to_text() and "EXTERN" in q.to_text() and "recorder" in q.to_text()
    sent = "\n".join(m.content for m in llm.requests[0].messages)
    assert "def add" in sent and secret not in sent and "--- file: calc.py ---" in sent and out.output["sent"]["secrets_redacted"] is True
    assert "A=1" not in sent and secret not in str(out) and secret not in r.audit_blob()
    assert llm.requests[0].max_tokens == 1200 and "DATA" in llm.requests[0].messages[0].content
    assert out.output["untrusted_content"]


def test_plan_never_sends_protected_files_and_respects_size_limits(tmp_path):
    llm = Recorder()
    r = make_rig(tmp_path, [ONCE] * 5, llm=llm, llm_context_chars=1000, files={"pyproject.toml": PYPROJECT, ".env": "A=1", "big.py": "x = 1\n" * 2000})
    r.start()
    assert code(r.run(action="plan", goal="g", paths=".env")) == "protected_path"
    assert code(r.run(action="plan", goal="g", paths="../x.py")) == "path_denied"
    assert code(r.run(action="plan", goal="g", paths="a,b,c,d,e,f")) == "invalid_input"
    assert code(r.run(action="plan", goal="")) == "invalid_input"
    assert r.run(action="plan", goal="shorten", paths="big.py").success
    assert sum(len(m.content) for m in llm.requests[-1].messages[1:]) <= 1000
    assert len(llm.requests) == 1


def test_plan_can_include_the_last_test_result_and_reports_llm_failures_safely(tmp_path):
    llm = Recorder()
    r = make_rig(tmp_path, [ONCE] * 6, llm=llm)
    r.start()
    r.provider.command_handler = lambda spec: CommandResult(1, "FAILED tests/test_calc.py::test_add - assert 1\n1 failed in 0.1s\n", "", False, False, 0.1)
    r.ok(action="test")
    r.ok(action="plan", goal="fix", include_tests=True)
    assert "test_add" in llm.requests[0].messages[1].content
    llm.fail = True
    out = r.run(action="plan", goal="fix")
    assert code(out) == "backend_error" and "abc123456789" not in out.error and "RuntimeError" in out.error


def test_baseline_rules_are_installed_and_can_be_switched_off_by_config_only(tmp_path):
    r = make_rig(tmp_path, [])
    ids = {x.id for x in r.engine.policy.rules}
    assert {"coding-baseline-special-write-confirm", "coding-baseline-delete-confirm", "coding-baseline-plan-confirm"} <= ids
    r2 = make_rig(tmp_path / "b", [], confirm_delete_each_time=False, confirm_llm_each_time=False)
    ids2 = {x.id for x in r2.engine.policy.rules}
    assert ids2 == {"coding-baseline-special-write-confirm"}  # the JARVIS/dependency rule has no switch


def test_a_replace_is_refused_if_the_file_changed_after_the_user_was_shown_the_change(started):
    """The user approved THIS edit of THIS content; if the file moved on in the meantime nothing is applied, even if old_text still matches."""
    path = str(started.file("calc.py"))
    changed = CALC + "\n# someone added this while the question was open\n"
    after_confirmation(started, lambda: started.provider.put(path, changed))
    out = started.run(action="write", path="calc.py", mode="replace", old_text="return a - b", new_text="return a + b")
    assert not out.success and code(out) == "file_changed"
    assert started.provider.text(path) == changed and started.provider.calls_named("write_file") == []


def test_every_write_needs_a_preview_first(started):
    kw = dict(path="n.py", mode="create", content="a\n")
    with pytest.raises(Exception) as exc:
        started.controller.plan("write", phase="perform", **kw)  # never previewed
    assert "file_changed" in str(exc.value)
    shown = started.controller.plan("write", **kw)
    performed = started.controller.plan("write", phase="perform", **kw)
    assert shown.digest == performed.digest
    with pytest.raises(Exception):
        started.controller.plan("write", phase="perform", **kw)  # a preview is used up by one perform: no second write on the same approval
