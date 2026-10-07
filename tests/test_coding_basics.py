"""Models, workspace rules, policy, project detection, diff model, provider contract, config, factory/bootstrap and CLI."""
import ntpath
import os

import pytest

from browser_util import ONCE as _unused  # noqa: F401  (keeps the shared test path set up)
from coding_util import CALC, ONCE, PYPROJECT, TEST_CALC, make_rig
from jarvis.bootstrap import build_core
from jarvis.coding import CodingProvider, CommandSpec, FileChange, SessionStatus, TestResult, Workspace
from jarvis.coding.controller import _count_lines, _symbols, _Session
from jarvis.coding.errors import CodingError, CodingErrorCode as EC
from jarvis.coding.factory import CodingSubsystem, build_coding, register_provider
from jarvis.coding.models import CommandResult, ProjectInfo, sha256_hex
from jarvis.coding.policy import (CodingPolicy, check_command_shape, classify, git_command, split_relative, validate_pytest_args,
                                  validate_unittest_args)
from jarvis.coding.providers.fake import FakeCodingProvider
from jarvis.coding.workspace import analyze_project, is_jarvis_repo, resolve_in_workspace, same_path, within
from jarvis.config import CodingSettings, load_settings
from jarvis.errors import ConfigError
from jarvis.interface.cli import run_command
from test_computer_integration import env_for, run_repl


def code_of(fn, *a):
    with pytest.raises(CodingError) as exc:
        fn(*a)
    return exc.value.code


# ---- models ---------------------------------------------------------------------------------------------------------------------------
def test_file_change_and_test_result_models():
    c = FileChange("src/a.py", "modify", "a" * 64, "b" * 64, 14, 2)
    assert c.summary() == "src/a.py: modify +14/-2"
    t = TestResult(("python", "-m", "pytest"), 1, False, False, "STDOUT-MARK", "STDERR-MARK", 1.5, False, "1 failed", ("t::f",))
    d = t.to_dict()
    assert d["exit_code"] == 1 and d["passed"] is False and d["timed_out"] is False and d["failures"] == ["t::f"] and d["stdout"] == "STDOUT-MARK"
    assert "MARK" not in repr(t)  # output can contain anything: never in a repr
    assert CommandResult(0, "o", "e").stdout == "o" and "secret-out" not in repr(CommandResult(0, "secret-out"))
    assert sha256_hex(b"x") == "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"


def test_workspace_and_session_models():
    from datetime import datetime, timezone
    ws = Workspace("w1", "/r", "python", datetime.now(timezone.utc))
    assert ws.is_jarvis is False and (ws.id, ws.root, ws.project_type) == ("w1", "/r", "python")
    s = _Session("c1", ws, ws.created_at)
    assert s.status is SessionStatus.ACTIVE and {x.value for x in SessionStatus} == {"active", "halted", "completed", "failed"}
    before = s.state()
    s.changes["a.py"] = FileChange("a.py", "create", None, "h1", 1, 0)
    assert s.state() != before
    s.changes["a.py"] = FileChange("a.py", "create", None, "h2", 1, 0)
    assert s.snapshot()["changed_files"] == ["a.py"] and s.snapshot()["actions"] == 0


def test_diff_counting_and_symbol_summary():
    added, removed, a_lines, r_lines = _count_lines("a\nb\nc\n", "a\nB\nc\nd\n")
    assert (added, removed, a_lines, r_lines) == (2, 1, ["B", "d"], ["b"])
    assert _count_lines("", "x\ny\n")[:2] == (2, 0) and _count_lines("x\n", "")[:2] == (0, 1) and _count_lines("same\n", "same\n")[:2] == (0, 0)
    assert _symbols(["def foo(x):", "    pass", "class Bar:", "async def baz():", "export function qux() {", "const f = (a) => a", "x = 1"]) == [
        "Funktion foo()", "Klasse Bar", "Funktion baz()", "Funktion qux()", "Funktion f()"]
    big = ["l%d" % i for i in range(30000)]
    assert _count_lines("\n".join(big), "\n".join(big + ["new"]))[:2] == (1, 0)  # huge files: coarse but bounded


# ---- path rules --------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["..", "../x", "a/../../x", "a/..", "./../x", "..\\x", "a\\..\\..\\x", "/etc/passwd", "\\windows", "C:\\Windows\\x", "c:/x",
                                 "C:x", "\\\\server\\share\\f", "//server/share/f", "\\\\?\\C:\\x", "\\\\.\\pipe\\x", "~/x", "~", "a/b:stream", "file.txt:ads",
                                 "CON", "nul.txt", "a/COM1", "lpt3.log", "x.", "a /b", "a/b ", "tab\tname", "new\nline", "x\x00y", "bi\u202edi",
                                 "zero\u200bwidth", "", "   ", ".", "./", "/", "a/" + "b" * 600])
def test_malformed_and_escaping_paths_are_rejected_on_every_platform(bad):
    assert code_of(split_relative, bad) in (EC.PATH_DENIED, EC.INVALID_INPUT)


def test_split_relative_normalises_harmless_spellings():
    assert split_relative("a//b/./c.py") == ["a", "b", "c.py"] and split_relative("a\\b\\c.py") == ["a", "b", "c.py"]
    assert split_relative("./src/x.py") == ["src", "x.py"] and split_relative("dir/..hidden") == ["dir", "..hidden"]
    for bad in (None, 5, b"x", ["a"]):
        assert code_of(split_relative, bad) == EC.INVALID_INPUT


@pytest.mark.parametrize("path,secret,protected,deps,binary", [
    (".env", 1, 0, 0, 0), (".ENV", 1, 0, 0, 0), (".env.production", 1, 0, 0, 0), ("app/.env.local", 1, 0, 0, 0), ("prod.env", 1, 0, 0, 0),
    (".env.example", 0, 0, 0, 0), (".env.sample", 0, 0, 0, 0), ("server.pem", 1, 0, 0, 0), ("A.KEY", 1, 0, 0, 0), ("id_rsa", 1, 0, 0, 0),
    ("ID_RSA.pub", 1, 0, 0, 0), ("id_ed25519", 1, 0, 0, 0), ("credentials.json", 1, 0, 0, 0), ("Credentials", 1, 0, 0, 0), ("secrets.yml", 1, 0, 0, 0),
    (".ssh/config", 1, 0, 0, 0), (".aws/credentials", 1, 0, 0, 0), (".npmrc", 1, 0, 0, 0), ("x.kdbx", 1, 0, 0, 0), ("service-account-prod.json", 1, 0, 0, 0),
    (".git/config", 0, 1, 0, 0), ("sub/.GIT/hooks/x", 0, 1, 0, 0), ("src/main.py", 0, 0, 0, 0), ("pyproject.toml", 0, 0, 1, 0),
    ("Requirements-dev.txt", 0, 0, 1, 0), ("package.json", 0, 0, 1, 0), ("yarn.lock", 0, 0, 1, 0), ("a/b.exe", 0, 0, 0, 1), ("lib.DLL", 0, 0, 0, 1),
    ("keys.txt", 0, 0, 0, 0), ("envrc.py", 0, 0, 0, 0)])
def test_path_classification(path, secret, protected, deps, binary):
    info = classify(split_relative(path))
    assert (info.secret, info.protected, info.deps, info.blocked_extension) == (bool(secret), bool(protected), bool(deps), bool(binary))


def test_workspace_containment_is_component_wise_and_platform_aware(monkeypatch):
    root = os.path.abspath("/ws/proj")
    assert within(root, root) and within(os.path.join(root, "a", "b"), root)
    assert not within(root + "-evil", root) and not within(root + "x/y", root) and not within(os.path.dirname(root), root)
    assert not within(os.path.abspath("/other"), root)
    assert same_path(root, os.path.join(root, "."))
    # Windows semantics, exercised with ntpath so the rule is tested on every platform
    assert ntpath.normcase("C:\\WS\\Proj") == ntpath.normcase("c:/ws/proj")
    assert ntpath.commonpath([ntpath.normcase("C:\\WS\\Proj\\A"), ntpath.normcase("c:\\ws\\proj")]) == ntpath.normcase("c:\\ws\\proj")


def test_resolve_in_workspace_with_symlinks_and_prefix_tricks():
    p = FakeCodingProvider()
    root = os.path.abspath("/ws/proj")
    p.put(os.path.join(root, "src", "a.py"), "x")
    p.put(os.path.abspath("/ws/proj-evil/secret.py"), "x")
    p.symlinks[os.path.join(root, "sib")] = os.path.abspath("/ws/proj-evil")
    p.symlinks[os.path.join(root, "up")] = os.path.abspath("/ws")
    p.symlinks[os.path.join(root, "inner")] = os.path.join(root, "src")
    ok = resolve_in_workspace(p, root, "src/a.py")
    assert ok.rel == "src/a.py" and ok.abs == os.path.join(root, "src", "a.py")
    assert resolve_in_workspace(p, root, "inner/a.py").abs == os.path.join(root, "src", "a.py")  # a link INSIDE the workspace is fine to read
    for bad in ("sib/secret.py", "up/x", "up/proj-evil/secret.py", "sib"):
        assert code_of(resolve_in_workspace, p, root, bad) == EC.PATH_DENIED
    link_to_env = FakeCodingProvider()
    link_to_env.put(os.path.join(root, ".env"), "K=1")
    link_to_env.symlinks[os.path.join(root, "innocent.txt")] = os.path.join(root, ".env")
    assert resolve_in_workspace(link_to_env, root, "innocent.txt").info.secret is True  # protected names cannot hide behind a link


# ---- runner policy --------------------------------------------------------------------------------------------------------------------------
def test_pytest_and_unittest_argument_allow_lists():
    assert validate_pytest_args(["-q", "-x", "tests/test_a.py::test_b[1-2]", "-k", "add and not slow", "--tb=short", "--maxfail=3"]) == [
        "-q", "-x", "tests/test_a.py::test_b[1-2]", "-k", "add and not slow", "--tb=short", "--maxfail=3"]
    for bad in (["-p", "x"], ["-c", "evil.ini"], ["--rootdir=/"], ["--basetemp=/tmp"], ["-o", "addopts=x"], ["--import-mode=append"], ["--pyargs"],
                ["-k"], ["-k", "a;b"], ["-m", "x|y"], ["--junitxml=/etc/x"], ["--log-file=/x"], ["--tb=evil"], ["--maxfail=abc"], ["$(id)"], ["a b;c"], ["`x`"]):
        assert code_of(validate_pytest_args, bad) == EC.COMMAND_NOT_ALLOWED, bad
    for bad in (["/etc"], ["../x.py"], ["tests/../../x.py"], [".env"], [".git/config"], ["C:\\x.py"]):
        assert code_of(validate_pytest_args, bad) in (EC.PATH_DENIED, EC.PROTECTED_PATH, EC.COMMAND_NOT_ALLOWED), bad
    assert validate_unittest_args(["-v", "discover", "-s", "tests", "-p", "test_*.py", "pkg.test_mod.TestX.test_y"]) == [
        "-v", "discover", "-s", "tests", "-p", "test_*.py", "pkg.test_mod.TestX.test_y"]
    for bad in (["-c", "x"], ["--evil"], ["a;b"], ["-s"], ["-s", "../x"], ["-p", "a b"], ["x/y"]):
        assert code_of(validate_unittest_args, bad) in (EC.COMMAND_NOT_ALLOWED, EC.PATH_DENIED, EC.INVALID_INPUT), bad


def test_runner_names_are_a_closed_list():
    pol = CodingPolicy(("pytest", "python -m pytest", "python -m unittest"))
    cmd = pol.build_test_command("python -m pytest", ["-q"], "/ws/proj", None)
    assert cmd.argv[0] == __import__("sys").executable and cmd.argv[1:4] == ("-m", "pytest", "-q") and "--rootdir" in cmd.argv
    assert pol.build_test_command("  pytest ", None, "/r", None).runner == "pytest"
    for bad in ("make test", "python -c print(1)", "bash -c x", "sh", "cmd /c dir", "powershell -Command x", "python -m pip install x", "pytest; ls", "npm test",
                "python", "", None, 5, ["pytest"], "PYTEST", "/usr/bin/pytest"):
        assert code_of(pol.build_test_command, bad, None, "/r", None) == EC.COMMAND_NOT_ALLOWED, bad
    assert code_of(CodingPolicy(("npm test",)).build_test_command, "npm test", None, "/r", None) == EC.RUNNER_UNAVAILABLE
    assert code_of(CodingPolicy(("npm test",)).build_test_command, "npm test", None, "/r", "C:\\n\\npm.CMD") == EC.RUNNER_UNAVAILABLE
    assert CodingPolicy(("npm test",)).build_test_command("npm test", None, "/r", "/usr/bin/npm").argv == ("/usr/bin/npm", "test")
    assert code_of(CodingPolicy(("npm test",)).build_test_command, "npm test", "-x", "/r", "/usr/bin/npm") == EC.COMMAND_NOT_ALLOWED
    assert CodingPolicy(("shell", "pytest")).test_commands == ("pytest",)  # unknown runner names are dropped, never run


def test_default_runner_follows_the_project():
    p = CodingPolicy(("pytest", "python -m pytest", "python -m unittest", "npm test"))
    assert p.default_runner("Python") == "python -m pytest" and p.default_runner("TypeScript") == "npm test"
    assert CodingPolicy(("python -m unittest",)).default_runner("JavaScript") == "python -m unittest"
    assert code_of(CodingPolicy(()).default_runner, "Python") == EC.COMMAND_NOT_ALLOWED


@pytest.mark.parametrize("exe", ["cmd.exe", "C:\\Windows\\System32\\cmd.exe", "C:\\Windows\\System32\\CMD.EXE", "/bin/sh", "/usr/bin/bash", "/bin/zsh", "powershell",
                                 "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe", "pwsh.exe", "/usr/bin/env", "/usr/bin/sudo", "C:\\x\\run.bat",
                                 "/tmp/x.cmd", "C:\\x\\a.ps1", "C:\\x\\a.vbs", "C:\\x\\wscript.exe", "C:\\Windows\\System32\\mshta.exe", "python", "pytest",
                                 "relative/python", "./python", ""])
def test_providers_refuse_shells_script_hosts_and_relative_programs(exe):
    assert code_of(check_command_shape, (exe, "x")) == EC.COMMAND_NOT_ALLOWED
    with pytest.raises(CodingError):
        FakeCodingProvider().run_command(CommandSpec((exe, "x"), "/ws", 1.0, 1000))


@pytest.mark.parametrize("argv", ["python -m pytest", ["python"], ("python", 5), (), ("/usr/bin/python", "a\x00b"), None, ("/usr/bin/python\x00", "a")])
def test_commands_must_be_argument_tuples_not_command_lines(argv):
    assert code_of(check_command_shape, argv) == EC.COMMAND_NOT_ALLOWED


def test_git_commands_are_read_only_and_hardened():
    for sub in ("status", "diff", "log"):
        argv = git_command(sub, None, 5, "/usr/bin/git")
        assert argv[0] == "/usr/bin/git" and "--no-pager" in argv and "core.fsmonitor=false" in argv and "protocol.ext.allow=never" in argv
        assert any(a.startswith("core.hooksPath=") for a in argv) and argv.index("--") < len(argv) - 1 and ":(exclude,glob)**/.env" in argv
    assert "--no-ext-diff" in git_command("diff", "a.py", 1, "/g") and "--no-textconv" in git_command("diff", "a.py", 1, "/g")
    assert git_command("log", None, 7, "/g")[git_command("log", None, 7, "/g").index("-n") + 1] == "7"
    for sub in ("commit", "push", "reset", "clean", "checkout", "rebase", "merge", "pull", "config", "stash", "apply", "am", "rm", "mv", "add", "gc", "-c", "", None):
        assert code_of(git_command, sub, None, 1, "/g") == EC.BLOCKED


# ---- project detection ----------------------------------------------------------------------------------------------------------------------
def project(files):
    p = FakeCodingProvider()
    root = os.path.abspath("/ws/p")
    p.dirs.add(root)
    for rel, text in files.items():
        p.put(os.path.join(root, rel), text)
    return p, root


def test_detects_python_node_javascript_typescript_and_unknown():
    p, r = project({"pyproject.toml": PYPROJECT + 'dependencies = ["fastapi"]\n', "tests/test_a.py": "x"})
    i = analyze_project(p, r)
    assert (i.language, i.framework, i.test_framework, i.is_jarvis) == ("Python", "fastapi", "pytest", False) and "pyproject.toml" in i.important_files
    p, r = project({"requirements.txt": "flask\npytest\n"})
    assert (analyze_project(p, r).framework, analyze_project(p, r).test_framework) == ("flask", "pytest")
    p, r = project({"setup.py": "x", "tests/test_x.py": "y"})
    assert analyze_project(p, r).test_framework == "unittest"
    p, r = project({"package.json": '{"name":"a","devDependencies":{"jest":"1"},"dependencies":{"express":"4"}}'})
    i = analyze_project(p, r)
    assert (i.language, i.framework, i.test_framework) == ("JavaScript", "express", "jest")
    p, r = project({"package.json": '{"dependencies":{"react":"18"},"devDependencies":{"typescript":"5","vitest":"1"}}', "tsconfig.json": "{}"})
    i = analyze_project(p, r)
    assert (i.language, i.framework, i.test_framework) == ("TypeScript", "react", "vitest") and "tsconfig.json" in i.important_files
    p, r = project({"package.json": '{"scripts":{"test":"node t.js"}}'})
    assert analyze_project(p, r).test_framework == "npm test" and analyze_project(p, r).framework == "Node.js"
    p, r = project({"package.json": "not json {"})
    assert analyze_project(p, r).language == "JavaScript"
    p, r = project({"tsconfig.json": "{}"})
    assert analyze_project(p, r).language == "TypeScript"
    p, r = project({"pyproject.toml": PYPROJECT, "package.json": "{}"})
    assert analyze_project(p, r).languages == ("Python", "JavaScript") and analyze_project(p, r).language == "Python"
    p, r = project({"notes.txt": "x"})
    assert analyze_project(p, r).language == "unknown" and analyze_project(p, r).to_dict()["important_files"] == []


def test_jarvis_repository_detection():
    p, r = project({"pyproject.toml": '[project]\nname = "jarvis-ai"\n', "src/jarvis/__init__.py": ""})
    assert is_jarvis_repo(p, r) and analyze_project(p, r).is_jarvis
    p, r = project({"src/jarvis/__init__.py": "", "src/jarvis/permissions/engine.py": ""})
    assert is_jarvis_repo(p, r)  # recognised by structure even without the metadata
    p, r = project({"pyproject.toml": '[project]\nname = "other"\n', "src/other/__init__.py": ""})
    assert not is_jarvis_repo(p, r)
    p, r = project({"pyproject.toml": "[broken"})
    assert not is_jarvis_repo(p, r)


# ---- provider contract --------------------------------------------------------------------------------------------------------------------------
def test_fake_provider_follows_the_same_primitive_rules_as_the_local_one(tmp_path):
    from jarvis.coding.providers.local import LocalProvider
    for prov, base in ((FakeCodingProvider(), os.path.abspath("/ws/c")), (LocalProvider(), str(tmp_path))):
        f = os.path.join(base, "d", "a.txt")
        prov.write_file(f, b"one", None)                        # create (+ parent dirs)
        with pytest.raises(CodingError) as e:
            prov.write_file(f, b"two", None)                    # exclusive
        assert e.value.code is EC.FILE_EXISTS
        with pytest.raises(CodingError) as e:
            prov.write_file(f, b"two", "0" * 64)                # hash guarded
        assert e.value.code is EC.FILE_CHANGED
        prov.write_file(f, b"two", sha256_hex(b"one"))
        assert prov.read_file(f, 100) == b"two" and prov.read_file(f, 2) == b"tw"
        assert [e.name for e in prov.scandir(os.path.dirname(f))] == ["a.txt"] and prov.stat(f).size == 3 and prov.stat(f + "x") is None
        with pytest.raises(CodingError) as e:
            prov.delete_file(f, "0" * 64)
        assert e.value.code is EC.FILE_CHANGED
        prov.delete_file(f, sha256_hex(b"two"))
        assert prov.stat(f) is None
        with pytest.raises(CodingError) as e:
            prov.delete_file(f, None)
        assert e.value.code is EC.FILE_NOT_FOUND
        assert isinstance(prov, CodingProvider) and prov.name in ("fake", "local")


def test_provider_interface_is_abstract():
    with pytest.raises(TypeError):
        CodingProvider()


# ---- configuration ------------------------------------------------------------------------------------------------------------------------------
def test_defaults_are_off_and_restrictive():
    c = load_settings(env={}).coding
    assert c == CodingSettings() and c.enabled is False and c.provider == "local" and c.workspace_roots == ()
    assert c.max_actions_per_session == 300 and c.test_commands == ("pytest", "python -m pytest", "python -m unittest")
    assert c.confirm_delete_each_time and c.confirm_llm_each_time and "npm test" not in c.test_commands


def test_file_and_env_configuration(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[coding]\nenabled = true\nprovider = "fake"\nmax_actions_per_session = 50\ntest_commands = ["pytest"]\nworkspace_roots = ["a", "b"]\n', encoding="utf-8")
    c = load_settings(f, env={"JARVIS_CODING_MAX_FILE_SIZE": "5000", "JARVIS_CODING_TEST_TIMEOUT": "9.5"}).coding
    assert (c.enabled, c.provider, c.max_actions_per_session, c.test_commands, c.workspace_roots) == (True, "fake", 50, ("pytest",), ("a", "b"))
    assert c.max_file_size == 5000 and c.test_timeout == 9.5


@pytest.mark.parametrize("toml", ['[coding]\nprovider = "docker"\n', '[coding]\ntest_commands = ["bash -c x"]\n', '[coding]\ntest_commands = ["powershell"]\n',
                                  '[coding]\ntest_commands = ["make test"]\n', '[coding]\ntest_commands = ["pytest; rm -rf /"]\n', '[coding]\nworkspace_roots = [""]\n',
                                  '[coding]\nmax_actions_per_session = -1\n', '[coding]\nmax_output_bytes = 5\n', '[coding]\nmax_file_size = 10\n',
                                  '[coding]\ntest_timeout = 0\n', '[coding]\ntest_timeout = 99999\n', '[coding]\nllm_context_chars = 1\n',
                                  '[coding]\nallow_shell = true\n', '[coding]\nskip_permissions = true\n', '[coding]\nallow_git_push = true\n',
                                  '[coding]\nallow_red = true\n', '[coding]\nauto_commit = true\n', '[coding]\nmax_search_results = 0\n'])
def test_invalid_coding_config_and_no_bypass_switches(tmp_path, toml):
    f = tmp_path / "c.toml"
    f.write_text(toml, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(f, env={})


# ---- factory / bootstrap / CLI ------------------------------------------------------------------------------------------------------------------------
def core_for(tmp_path, **extra):
    return build_core(load_settings(env=env_for(tmp_path, JARVIS_CODING_ENABLED="true", JARVIS_CODING_PROVIDER="fake", **extra)))


def test_disabled_by_default_registers_nothing(tmp_path):
    core = build_core(load_settings(env=env_for(tmp_path)))
    sub = core.subsystems["coding"]
    assert sub.status == "disabled" and "coding" not in core.tools and not sub.available and sub.halt() is False and sub.stop() is False
    out = run_command(core, "/coding")
    assert "deaktiviert" in out and "JARVIS_CODING_ENABLED" in out


def test_enabled_registers_one_protected_tool_and_baseline_rules_and_uses_the_core_llm(tmp_path):
    core = core_for(tmp_path)
    sub = core.subsystems["coding"]
    assert sub.status == "enabled" and sub.tool_names == ["coding"] and "coding" in core.tools
    assert {"coding-baseline-special-write-confirm", "coding-baseline-delete-confirm", "coding-baseline-plan-confirm"} <= {r.id for r in core.permissions.policy.rules}
    assert next(t for t in core.tools.describe_all() if t["name"] == "coding")["permission"] == "green"
    assert sub.controller._llm is core.provider and sub.controller.workspace_roots == (os.path.realpath(str(tmp_path / "ws")),)


def test_unknown_or_broken_providers_and_failed_installs_do_not_break_startup(tmp_path, monkeypatch):
    from dataclasses import replace
    from jarvis.errors import ToolError
    from jarvis.permissions import PermissionEngine, Policy
    from jarvis.tools import ToolRegistry
    import jarvis.coding.factory as fac

    def boom(settings):
        raise RuntimeError("provider exploded with secret=abc12345")
    register_provider("exploding", boom)
    base = load_settings(env={})
    for provider in ("exploding", "nope"):
        s = replace(base, coding=replace(base.coding, enabled=True, provider=provider)) if provider == "exploding" else None
        if s is None:
            sub = build_coding(replace(base, coding=replace(base.coding, enabled=True)), ToolRegistry(PermissionEngine()), PermissionEngine())
            fac._BUILDERS.pop("local")
            try:
                sub = build_coding(replace(base, coding=replace(base.coding, enabled=True)), ToolRegistry(PermissionEngine()), PermissionEngine())
            finally:
                fac.register_provider("local", fac._build_local)
            assert sub.status == "unavailable" and "unknown coding provider" in sub.reason
            continue
        sub = build_coding(s, ToolRegistry(PermissionEngine()), PermissionEngine())
        assert sub.status == "unavailable" and "abc12345" not in sub.reason

    def broken(registry, controller):
        raise ToolError("cannot register")
    monkeypatch.setattr(fac, "register_coding_tools", broken)
    engine = PermissionEngine(policy=Policy())
    before = engine.policy.rules
    sub = build_coding(replace(base, coding=replace(base.coding, enabled=True, provider="fake")), ToolRegistry(engine), engine)
    assert sub.status == "unavailable" and engine.policy.rules == before  # no half-installed safety rules


def test_cli_status_halt_resume_stop(tmp_path):
    core = core_for(tmp_path)
    ws = tmp_path / "ws"
    sub = core.subsystems["coding"]
    sub.controller._provider.dirs.add(os.path.realpath(str(ws)))
    status = run_command(core, "/coding")
    assert "Coding Agent: aktiv" in status and "Keine Sitzung" in status and "/run coding action=start" in status
    out = run_repl(core, [f"/run coding action=start workspace={ws}", "j", "/coding", "/exit"])
    for expected in ("Workspace:", "Session: c1-", "Status: active", "Actions: ", "Changed files: 0", "Tests: 0"):
        assert expected in out
    assert "angehalten" in run_command(core, "/coding halt") and "ANGEHALTEN" in run_command(core, "/coding") and "Status: halted" in run_command(core, "/coding")
    assert "fortgesetzt" in run_command(core, "/coding resume") and "Status: active" in run_command(core, "/coding")
    assert "beendet" in run_command(core, "/coding stop") and "Keine laufende" in run_command(core, "/coding stop")


def test_cli_uses_the_ordinary_run_and_permission_path(tmp_path):
    core = core_for(tmp_path)
    ws = tmp_path / "ws"
    core.subsystems["coding"].controller._provider.dirs.add(os.path.realpath(str(ws)))
    out = run_repl(core, [f"/run coding action=start workspace={ws}", "n", f"/run coding action=start workspace={ws}", "j", "/run coding action=info",
                          "/run coding action=read path=../x", "/run coding action=git sub=push", "/exit"])
    assert out.count("Erlauben?") == 2 and "the user declined" in out and "OK: {'session'" in out and "OK: {'root'" in out
    assert "[path_denied]" in out and "RED actions are never permitted" in out


def test_cli_help_mentions_coding(tmp_path):
    assert "/coding" in run_command(core_for(tmp_path), "/help")
