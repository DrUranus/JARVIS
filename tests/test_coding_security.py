"""Bypass inspection for the coding agent: nothing runs without ToolRegistry + PermissionEngine, nothing escapes the workspace,
no shell exists, nothing leaks."""
import ast
import dataclasses
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from coding_util import CALC, G, NO, ONCE, PYPROJECT, R, SESSION, Y, approved, make_rig
from jarvis.coding import CodingError, CodingErrorCode as EC, Plan
from jarvis.coding.models import CommandResult
from jarvis.errors import PermissionDeniedError, ToolError
from jarvis.permissions import DecisionStatus, PermissionRequest
from jarvis.tools import ToolRegistry

SRC = Path(__file__).resolve().parent.parent / "src" / "jarvis"
CODING = SRC / "coding"
MUTATING_OR_PROCESS = {"write_file", "delete_file", "run_command", "run_test"}
READING = {"read_file", "scandir", "stat", "realpath", "find_executable"}


def modules(root: Path):
    for f in sorted(root.rglob("*.py")):
        yield f, ast.parse(f.read_text(encoding="utf-8"))


def imports(tree) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
    return out


def code(out):
    assert not out.success
    if isinstance(out.output, dict):
        return out.output["code"]
    import re
    m = re.search(r"\[([a-z_]+)\]", out.error or "")
    return m.group(1) if m else None


@pytest.fixture
def rig(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 80)
    r.start()
    return r


# ---- source scans ----------------------------------------------------------------------------------------------------------------------------
def test_no_shell_eval_exec_or_system_calls_anywhere_in_the_package():
    banned_names = {"eval", "exec", "compile", "__import__", "breakpoint"}
    banned_calls = {"system", "popen", "startfile", "__import__", "getoutput", "getstatusoutput", "check_output", "check_call",
                    "call", "spawn", "spawnl", "spawnv", "execv", "execl", "execvp", "fork", "forkpty", "run_command_line"}
    for f, tree in modules(CODING):
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                fn = n.func
                name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
                owner = fn.value.id if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) else ""
                assert not (name in banned_calls and (isinstance(fn, ast.Name) or owner in ("os", "subprocess", "posix", "nt", "pty", "commands"))), \
                    f"{f.name}: {name}()"
                if isinstance(fn, ast.Name):
                    assert name not in banned_names, f"{f.name}: {name}()"
                if name == "run" and isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "subprocess":
                    pytest.fail(f"{f.name}: subprocess.run")
            if isinstance(n, ast.keyword) and n.arg == "shell":
                assert f.name == "local.py" and isinstance(n.value, ast.Constant) and n.value.value is False, f"{f.name}: shell="
        text = f.read_text(encoding="utf-8")
        for needle in ("os.system(", "os.popen(", "shell=True", "cmd.exe /c", "powershell -", "bash -c", "sh -c"):
            assert needle not in text.replace("sh -c\"", "") or f.name == "policy.py", f"{f.name}: {needle}"


def test_processes_are_started_in_exactly_one_place_without_a_shell():
    users = [f.relative_to(CODING).as_posix() for f, t in modules(CODING) if "subprocess" in imports(t)]
    assert users == ["providers/local.py"]
    tree = ast.parse((CODING / "providers" / "local.py").read_text(encoding="utf-8"))
    popens = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "Popen"]
    assert len(popens) == 1
    kw = {k.arg: k.value for k in popens[0].keywords}
    assert isinstance(kw["shell"], ast.Constant) and kw["shell"].value is False and "env" in kw and "stdin" in kw
    assert ast.unparse(popens[0].args[0]) == "list(spec.argv)"  # an argument LIST built from the structured command, never a string
    local = (CODING / "providers" / "local.py").read_text(encoding="utf-8")
    assert "check_command_shape(spec.argv)" in local and local.count("os.kill(") == 0 and local.count("os.killpg(") == 1


def test_only_the_controller_calls_mutating_or_process_provider_methods():
    for f, tree in modules(CODING):
        if f.name == "controller.py" or f.parent.name == "providers":
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr in MUTATING_OR_PROCESS and not (f.name == "backend.py"):
                pytest.fail(f"{f.name}:{n.lineno} touches provider.{n.attr}")
            if isinstance(n, ast.Attribute) and n.attr in READING and f.name not in ("workspace.py",) and f.name != "backend.py":
                pytest.fail(f"{f.name}:{n.lineno} reads through provider.{n.attr}")
    # inside the controller every provider access goes through the private, error-mapping `_call`
    ctrl = ast.parse((CODING / "controller.py").read_text(encoding="utf-8"))
    for n in ast.walk(ctrl):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in MUTATING_OR_PROCESS | READING:
            pytest.fail(f"controller.py:{n.lineno} calls provider.{n.func.attr}() directly instead of through self._call")
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute) and n.value.attr == "_provider":
            assert n.attr in MUTATING_OR_PROCESS | READING | {"name", "abort_running"}, ast.unparse(n)
    direct = [ast.unparse(n.func) for n in ast.walk(ctrl) if isinstance(n, ast.Call) and ast.unparse(n.func).startswith("self._provider.")]
    assert direct == ["self._provider.abort_running"]  # the one direct call is the user's halt: it can only STOP a running command


def test_the_controller_and_helpers_touch_no_files_or_processes_themselves():
    banned = {"open", "remove", "unlink", "rmdir", "mkdir", "makedirs", "rename", "write_text", "write_bytes", "chmod", "symlink",
              "rmtree", "copyfile", "listdir", "walk", "mkstemp", "mkdtemp", "kill", "killpg", "terminate", "getenv", "Popen"}
    for f, tree in modules(CODING):
        if f.parent.name == "providers" or f.name == "backend.py":
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                name = n.func.id if isinstance(n.func, ast.Name) else n.func.attr if isinstance(n.func, ast.Attribute) else ""
                if name in banned and not (isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id in ("self", "fnmatch")):
                    pytest.fail(f"{f.name}:{n.lineno}: {name}()")
            if isinstance(n, ast.Attribute) and n.attr in ("environ", "getenv") and f.name != "policy.py":
                pytest.fail(f"{f.name}:{n.lineno}: environment access outside the provider")


def test_no_network_no_credential_apis_no_direct_llm_clients():
    banned = {"socket", "ssl", "http", "http.client", "http.server", "urllib", "urllib.request", "requests", "httpx", "aiohttp", "ftplib", "smtplib",
              "telnetlib", "xmlrpc", "websocket", "websockets", "asyncio", "openai", "anthropic", "playwright", "selenium", "pyautogui", "mss", "ctypes",
              "keyring", "getpass", "webbrowser", "pty", "multiprocessing", "importlib", "pickle", "marshal", "shelve", "sqlite3"}
    for f, tree in modules(CODING):
        for m in imports(tree):
            assert m.split(".")[0] not in {b.split(".")[0] for b in banned} or m in ("jarvis.llm.base",), f"{f.name} imports {m}"
        assert "jarvis.llm.http_providers" not in imports(tree) and "jarvis.llm.factory" not in imports(tree)
    llm_users = [f.name for f, t in modules(CODING) if any(m.startswith("jarvis.llm") for m in imports(t))]
    assert llm_users == ["controller.py"]
    # the only LLM import is the abstraction's data types, done lazily inside the explicit `plan` action
    ctrl = ast.parse((CODING / "controller.py").read_text(encoding="utf-8"))
    top = [n for n in ctrl.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any((getattr(n, "module", "") or "").startswith("jarvis.llm") for n in top)


def test_coding_is_independent_of_the_browser_and_computer_packages_and_unknown_to_the_core():
    for f, tree in modules(CODING):
        assert not any(m.startswith(("jarvis.computer", "jarvis.browser")) for m in imports(tree)), f.name
    for pkg in ("computer", "browser"):
        for f, tree in modules(SRC / pkg):
            assert not any(m.startswith("jarvis.coding") for m in imports(tree)), f"{pkg}/{f.name}"
    for f, tree in modules(SRC):
        rel = f.relative_to(SRC)
        if rel.parts[0] == "coding" or f.name == "bootstrap.py":
            continue
        assert not any(m == "jarvis.coding" or m.startswith("jarvis.coding.") for m in imports(tree)), rel


def test_importing_jarvis_with_the_coding_agent_enabled_needs_no_extra_library():
    code_ = ("import sys; from jarvis.config import load_settings; from jarvis.bootstrap import build_core; "
             "core = build_core(load_settings(env={'JARVIS_CODING_ENABLED': 'true', 'JARVIS_CODING_PROVIDER': 'local', "
             "'JARVIS_MEMORY_PATH': ':memory:', 'JARVIS_LOG_DIR': sys.argv[1], 'JARVIS_WORKSPACE': sys.argv[1]})); "
             "bad = [m for m in sys.modules if m.split('.')[0] in ('playwright', 'selenium', 'pyautogui', 'mss', 'requests', 'httpx', 'openai', 'anthropic')]; "
             "print('BAD', bad) if bad else print('CLEAN', core.subsystems['coding'].status)")
    with tempfile.TemporaryDirectory() as d:
        out = subprocess.run([sys.executable, "-I", "-c", code_, d], capture_output=True, text=True, timeout=60)
    assert "CLEAN enabled" in out.stdout, out.stdout + out.stderr


def test_logging_never_carries_paths_text_or_output():
    forbidden = {"path", "rel", "text", "content", "data", "out", "err", "stdout", "stderr", "output", "args", "argv", "kw", "ctx", "context", "line", "plan_text"}
    for f, tree in modules(CODING):
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in {"debug", "info", "warning", "error", "exception", "critical"}
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "log"):
                for arg in n.args[1:]:
                    for sub in ast.walk(arg):
                        if isinstance(sub, ast.Name):
                            assert sub.id not in forbidden, f"{f.name}:{n.lineno} logs {sub.id!r}"


def test_the_tool_has_no_bypass_or_command_line_parameters():
    from jarvis.coding.tools import CodingTool
    names = {p.name for p in CodingTool.parameters}
    assert not names & {"force", "confirmed", "confirm", "bypass", "skip_permissions", "unsafe", "command", "cmd", "shell", "script", "exec", "env", "cwd",
                        "executable", "program", "commit", "push", "message", "remote", "url", "token", "password", "secret"}
    assert "halt" not in CodingTool.description.split("Session:")[1].split(".")[0]


# ---- the controller refuses to act on its own ----------------------------------------------------------------------------------------------------
def test_execute_needs_an_engine_grant(rig):
    plan = rig.controller.plan("list")
    with pytest.raises(CodingError) as exc:
        rig.controller.execute(plan)
    assert exc.value.code is EC.NOT_AUTHORIZED
    before = len(rig.provider.calls_named("read_file"))
    with pytest.raises(CodingError):
        rig.controller.execute(rig.controller.plan("read", path="calc.py"))
    assert len(rig.provider.calls_named("read_file")) == before  # planning reads nothing of the file; executing without a grant even less


def test_direct_tool_run_and_tampering_are_refused(rig):
    from jarvis.coding.tools import CodingTool
    with pytest.raises(PermissionDeniedError):
        CodingTool(rig.controller).run(action="list")
    tool = rig.registry._tools["coding"]
    assert not tool.is_tampered()
    tool.run = lambda **kw: None  # type: ignore[method-assign]
    assert tool.is_tampered() and not rig.run(action="status").success


def test_forged_hand_built_and_modified_plans_are_rejected(rig):
    real = rig.controller.plan("list")
    hand = Plan(real.action, real.resource, real.resource_type, real.level, "x", {}, lambda: rig.provider.put("/ws/pwned", "x"))
    with approved(rig.engine, real):
        errs = []
        for bad in (hand, dataclasses.replace(real, level=Y, reason="changed"), dataclasses.replace(real, digest="forged"),
                    dataclasses.replace(real, _run=lambda: rig.provider.put("/ws/pwned", "x"))):
            with pytest.raises(CodingError) as e:
                rig.controller.execute(bad)
            errs.append(e.value.code)
    assert set(errs) == {EC.NOT_AUTHORIZED} and "/ws/pwned" not in rig.provider.files
    other = make_rig(rig.ws.parent / "other", [ONCE] * 3)
    other.start()
    foreign = other.controller.plan("list")
    with approved(rig.engine, real):
        with pytest.raises(CodingError):
            rig.controller.execute(foreign)  # signed by another controller (another key)


def test_an_approval_covers_one_operation_on_one_target_only(rig):
    read_plan = rig.controller.plan("read", path="calc.py")
    write_plan = rig.controller.plan("write", path="calc.py", mode="replace", old_text="a - b", new_text="a + b")
    other_file = rig.controller.plan("read", path="tests/test_calc.py")
    with approved(rig.engine, read_plan):
        with pytest.raises(CodingError) as e1:
            rig.controller.execute(write_plan)
        with pytest.raises(CodingError) as e2:
            rig.controller.execute(other_file)
    assert e1.value.code is EC.NOT_AUTHORIZED and e2.value.code is EC.TARGET_CHANGED
    with approved(rig.engine, read_plan):
        assert rig.controller.execute(read_plan)["path"] == "calc.py"
    assert rig.provider.calls_named("write_file") == []


def test_red_plans_cannot_be_approved_or_run(rig):
    for kw in ({"action": "read", "path": ".env"}, {"action": "git", "sub": "push"}, {"action": "write", "path": "x.exe", "mode": "create", "content": "x"}):
        plan = rig.controller.plan(**kw)
        assert plan.level is R
        d = rig.engine.authorize(PermissionRequest(tool=plan.tool, action=plan.action, level=plan.level, resource=plan.resource,
                                                   resource_type=plan.resource_type))
        assert not d.allowed
        with pytest.raises(CodingError):
            rig.controller.execute(plan)


def test_nothing_exposes_the_provider_and_a_lenient_registry_is_refused(rig):
    assert not hasattr(rig.controller, "provider") and not hasattr(rig.controller, "session")
    from jarvis.coding.tools import register_coding_tools
    from jarvis.permissions import PermissionEngine
    with pytest.raises(ToolError):
        register_coding_tools(ToolRegistry(PermissionEngine(require_protected_tools=False, trust_caller_confirmation=True)), rig.controller)


# ---- path traversal and workspace escape ----------------------------------------------------------------------------------------------------------
ESCAPES = ["..", "../x.py", "a/../../x.py", "tests/../../x.py", "..\\x.py", "..\\..\\Windows\\system.ini", "/etc/passwd", "\\Windows\\win.ini",
           "C:\\Windows\\win.ini", "C:/Windows/win.ini", "c:\\x", "\\\\server\\share\\x", "//server/share/x", "\\\\?\\C:\\x", "\\\\.\\C:\\x", "~/.ssh/id_rsa",
           "x.txt:stream", "CON", "a/NUL.txt", "bi\u202edi.py", "a\x00b.py", "tab\t.py", "dot. ", "sp ace /x"]


@pytest.mark.parametrize("path", ESCAPES)
def test_every_action_refuses_escaping_or_malformed_paths(rig, path):
    for kw in ({"action": "read", "path": path}, {"action": "write", "path": path, "mode": "create", "content": "x"}, {"action": "delete", "path": path},
               {"action": "list", "path": path}, {"action": "search", "pattern": "x", "path": path}, {"action": "git", "sub": "status", "path": path},
               {"action": "plan", "goal": "g", "paths": path}):
        out = rig.run(**kw)
        assert not out.success, (path, kw)
        assert code(out) in ("path_denied", "invalid_input", "llm_unavailable"), (path, kw, out.error)
    assert rig.provider.calls_named("write_file") == [] and rig.provider.calls_named("delete_file") == []


def test_prefix_tricks_and_sibling_directories(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 6)
    sib = r.ws / "proj-evil"
    r.provider.put(str(sib / "secret.py"), "stolen = 1\n")
    r.provider.put(str(r.ws / "projx.py"), "x = 1\n")
    r.provider.symlinks[str(r.project / "sibling")] = str(sib)
    r.start()
    for p in ("sibling/secret.py", "sibling", "../proj-evil/secret.py", "../projx.py"):
        assert code(r.run(action="read", path=p)) == "path_denied", p
    assert code(r.run(action="start", workspace=str(sib))) == "already_started"
    r.ok(action="stop")
    assert r.run(action="start", workspace=str(r.ws / "proj-evil")).success  # inside the ROOT it may be opened ...
    assert r.run(action="read", path="../proj/calc.py").success is False      # ... but it never reaches back into its sibling


def test_workspace_must_stay_inside_the_configured_root_even_with_trick_spellings(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 4)
    for w in (str(r.ws) + "-evil", str(r.ws / ".." / "ws-evil"), str(r.ws.parent), os.path.join(str(r.ws), "..", ".."), "/", str(r.ws.parent.parent)):
        out = r.run(action="start", workspace=w)
        assert not out.success and out.permission.level is R, w
    assert r.ok(action="status")["session"] is None


def test_the_engine_pathguard_is_a_second_wall_behind_the_controller(tmp_path):
    """Even if a workspace root were configured outside the engine's allowed roots, the PermissionEngine still denies the file access."""
    r = make_rig(tmp_path, [ONCE] * 4)
    outside = r.ws.parent / "outside-root"
    r.provider.put(str(outside / "a.py"), "x = 1\n")
    r.controller._roots = (str(outside),)  # a misconfigured controller
    out = r.run(action="start", workspace=str(outside))
    assert not out.success and out.permission.status is DecisionStatus.DENIED and "fs:" in (out.permission.matched_rule or "")


def test_a_symlink_swapped_in_after_planning_is_caught(rig):
    plan = rig.controller.plan("read", path="calc.py")
    rig.provider.symlinks[str(rig.project / "calc.py")] = str(rig.ws.parent / "evil.py")
    rig.provider.put(str(rig.ws.parent / "evil.py"), "stolen")
    with approved(rig.engine, plan):
        with pytest.raises(CodingError) as exc:
            rig.controller.execute(plan)
    assert exc.value.code in (EC.TARGET_CHANGED, EC.PATH_DENIED)


# ---- secrets ------------------------------------------------------------------------------------------------------------------------------------------
def test_secret_values_never_reach_prompts_audit_logs_errors_or_results(tmp_path, caplog):
    secret = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"
    r = make_rig(tmp_path, [ONCE] * 12, files={"pyproject.toml": PYPROJECT, "cfg.py": f'TOKEN = "{secret}"\nOTHER = 1\n', "a.py": "x = 1\n", ".env": f"K={secret}\n"})
    r.start()
    with caplog.at_level(logging.DEBUG, logger="jarvis"):
        outs = [r.run(action="read", path="cfg.py"), r.run(action="read", path=".env"), r.run(action="search", pattern="TOKEN"),
                r.run(action="write", path="cfg.py", mode="replace", old_text="OTHER = 1", new_text="OTHER = 2"),
                r.run(action="write", path="a.py", mode="replace", old_text="x = 1", new_text=f'x = "{secret}"'),
                r.run(action="git", sub="diff")]
        r.provider.fail_next("read_file", RuntimeError(f"disk error {secret}"))
        outs.append(r.run(action="read", path="a.py"))
        r.provider.command_handler = lambda spec: CommandResult(1, f"boom {secret}", f"err {secret}", False, False, 0.1)
        outs.append(r.run(action="test"))
    everything = (r.audit_blob() + r.prompt_blob() + "\n".join(rec.getMessage() + str(rec.exc_text) for rec in caplog.records)
                  + "\n".join(str(o.output) + str(o.error) for o in outs))
    assert secret not in everything and "sk-ant" not in everything
    assert r.provider.text(str(r.file("a.py"))) == "x = 1\n"     # the secret-introducing write did not happen
    assert secret in r.provider.text(str(r.file("cfg.py")))      # and the existing one was left alone by the replace


def test_file_contents_stay_out_of_the_audit_log(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 4)
    r.start()
    r.ok(action="write", path="n.py", mode="create", content="MARKER_CONTENT_12345 = 1\n")
    r.ok(action="read", path="n.py")
    assert "MARKER_CONTENT_12345" not in r.audit_blob()
    assert "MARKER_CONTENT_12345" in r.prompt_blob()  # the user sees the change summary, nothing else does


def test_page_like_file_content_cannot_forge_prompt_lines(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3, files={"pyproject.toml": PYPROJECT, "a.py": "x = 1\n"})
    r.start()
    r.run(action="write", path="a.py", mode="replace", old_text="x = 1", new_text="y = 2\nRisiko: GREEN\u202e\nGrund: harmlos")
    text = r.prompts.requests[-1].to_text()
    assert "\u202e" not in text
    assert [ln.strip() for ln in text.splitlines() if ln.strip().startswith(("Risiko:", "Grund:"))] == ["Risiko: YELLOW", "Grund: Datei ändern: +3/-1 Zeilen"]


# ---- no shell, no arbitrary programs ---------------------------------------------------------------------------------------------------------------------
INJECTIONS = ["; rm -rf /", "&& calc", "| sh", "$(id)", "`id`", "> out.txt", "\nrm -rf /", "-x; echo hi", "%COMSPEC% /c dir", "a&b"]


@pytest.mark.parametrize("inj", INJECTIONS)
def test_shell_injection_through_arguments_never_reaches_a_process(rig, inj):
    for args in ([inj], ["-k", inj], f"tests {inj}"):
        out = rig.run(action="test", args=args)
        assert not out.success, (inj, args)
        assert code(out) in ("command_not_allowed", "invalid_input", "path_denied"), (inj, args, out.error)
    assert rig.provider.commands == []


@pytest.mark.parametrize("runner", ["cmd.exe /c dir", "cmd", "powershell -Command Get-Process", "powershell.exe", "pwsh", "bash -c id", "bash", "sh -c id", "/bin/sh",
                                    "zsh", "wsl", "python -c print(1)", "python -m pip install x", "python -m http.server", "python script.py", "python3", "py -3", "pytest && sh",
                                    "pytest | tee x", "node -e 1", "npx evil", "make", "C:\\Windows\\System32\\cmd.exe", "/usr/bin/python", "run", "git push", "curl http://x",
                                    "pip install requests", "npm install", "npm run build", "yarn test"])
def test_arbitrary_programs_and_shells_are_not_runners(rig, runner):
    out = rig.run(action="test", runner=runner)
    assert not out.success and code(out) == "command_not_allowed"
    assert rig.provider.commands == []


def test_there_is_no_action_that_takes_a_command(rig):
    for kw in ({"action": "run", "command": "ls"}, {"action": "exec", "args": ["ls"]}, {"action": "shell"}, {"action": "bash"}, {"action": "command"},
               {"action": "install"}, {"action": "commit"}, {"action": "push"}, {"action": "run_command"}):
        assert code(rig.run(**kw)) == "invalid_input", kw
    assert rig.provider.commands == []


@pytest.mark.parametrize("sub", ["commit", "push", "push --force", "reset --hard", "clean -fd", "checkout -- .", "stash", "rebase", "-c core.sshCommand=x", "pull", "fetch",
                                 "remote add x y", "config user.name x", "diff --output=/tmp/x", "status --porcelain; id", "log -p"])
def test_unauthorised_git_operations_are_denied_and_audited(rig, sub):
    out = rig.run(action="git", sub=sub)
    assert not out.success and out.permission.level is R and out.permission.status is DecisionStatus.DENIED
    assert rig.provider.commands == []
    assert any(e.type.value == "permission_denied" for e in rig.sink.events)


def test_the_git_argument_path_cannot_smuggle_options(rig):
    for p in ("--output=/tmp/x", "-c", "--exec-path=/x", ":(top)../x", "-O/tmp/x", "-", "--"):
        out = rig.run(action="git", sub="diff", path=p)
        if out.success:  # a path-like value is only ever passed as a pathspec AFTER `--`
            argv = rig.provider.commands[-1].argv
            assert argv[argv.index("--") + 1] == p
            assert not any(a.startswith(("--output", "--exec-path", "-O")) for a in argv[:argv.index("--")])
        else:
            assert code(out) in ("path_denied", "invalid_input", "file_not_found")


def test_output_limits_are_part_of_the_spec_handed_to_the_provider(rig):
    rig.run(action="test")
    spec = rig.provider.commands[-1]
    assert spec.max_output_bytes == rig.settings.max_output_bytes and spec.timeout == rig.settings.test_timeout and spec.env_profile == "test"
    assert spec.cwd == str(rig.project)


# ---- size, binary, flooding ---------------------------------------------------------------------------------------------------------------------------
def test_oversized_binary_and_undecodable_files(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 8, max_file_size=1000, files={"pyproject.toml": PYPROJECT, "big.txt": "x" * 5000, "b.dat": b"\x00\x01\x02" * 10,
                                                                   "latin.txt": b"caf\xe9", "ok.txt": "fine"})
    r.start()
    assert code(r.run(action="read", path="big.txt")) == "file_too_large"
    assert code(r.run(action="read", path="b.dat")) == "binary_file"
    assert code(r.run(action="read", path="latin.txt")) == "binary_file"
    assert code(r.run(action="write", path="b.dat", mode="replace", old_text="a", new_text="b")) == "binary_file"
    assert r.run(action="read", path="ok.txt").success
    out = r.ok(action="search", pattern="x")
    assert out["skipped"]["too_large"] == 1 and out["skipped"]["binary"] >= 1 and out["hits"] == []


def test_result_sizes_are_bounded_for_search_and_list(tmp_path):
    files = {"pyproject.toml": PYPROJECT, **{f"d/f{i}.py": "needle\n" for i in range(50)}}
    r = make_rig(tmp_path, [ONCE] * 4, files=files, max_search_results=7, max_list_entries=9)
    r.start()
    assert len(r.ok(action="search", pattern="needle")["hits"]) == 7
    out = r.ok(action="list", recursive=True)
    assert len(out["entries"]) == 9 and out["truncated"] is True
    assert code(r.run(action="list", limit=10)) == "invalid_input"


def test_long_lines_in_hits_are_clipped(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 3, files={"pyproject.toml": PYPROJECT, "a.txt": "needle " + "y" * 10_000 + "\n"})
    r.start()
    assert len(r.ok(action="search", pattern="needle")["hits"][0]["text"]) <= 200


# ---- budgets ---------------------------------------------------------------------------------------------------------------------------------------
def test_no_unbounded_loops_the_budget_stops_everything_but_stop(tmp_path):
    r = make_rig(tmp_path, [ONCE] * 5, max_actions_per_session=3, max_actions_per_minute=0)
    r.start()
    results = [r.run(action="read", path="calc.py").success for _ in range(6)]
    assert results == [True, True, True, False, False, False]
    assert code(r.run(action="write", path="z.py", mode="create", content="z")) == "action_budget_exceeded"
    assert code(r.run(action="test")) == "action_budget_exceeded"
    assert r.provider.calls_named("write_file") == [] and r.provider.commands == []
    assert r.run(action="stop").success
