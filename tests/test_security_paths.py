"""Filesystem safety foundation: normalisation, traversal, symlinks, roots; host normalisation."""
import os
import sys

import pytest

from jarvis.errors import InvalidRequestError, PolicyError
from jarvis.permissions import PathGuard
from jarvis.permissions.paths import is_within
from jarvis.permissions.resources import host_matches, normalize_host

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink semantics")


@pytest.fixture
def ws(tmp_path):
    d = tmp_path / "ws"
    (d / "sub").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    return d


@pytest.fixture
def guard(ws):
    return PathGuard([ws], base_dir=ws)


# ---- normalisation: absolute vs relative, equivalent spellings ---------------------------------------
def test_relative_path_inside_root(guard, ws):
    c = guard.check("a.txt")
    assert c.ok and c.resolved == str(ws / "a.txt") and c.code == "ok"


def test_absolute_path_inside_root(guard, ws):
    assert guard.check(str(ws / "sub" / "a.txt")).ok


def test_root_itself_is_allowed(guard, ws):
    assert guard.check(str(ws)).ok and guard.check(".").ok


@pytest.mark.parametrize("spelling", ["sub/a.txt", "./sub/a.txt", "sub//a.txt", "sub/./a.txt", "sub/../sub/a.txt",
                                      "sub/x/../a.txt", "sub/a.txt/", "./sub/../sub/./a.txt"])
def test_equivalent_spellings_resolve_to_the_same_path(guard, ws, spelling):
    c = guard.check(spelling)
    assert c.ok and c.resolved == str(ws / "sub" / "a.txt")


def test_pathlike_objects_are_accepted(guard, ws):
    assert guard.check(ws / "x.txt").ok


# ---- traversal ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["../outside/x.txt", "..", "../..", "sub/../../outside", "sub/../../../etc/passwd",
                                  "./../outside", "a/../../b", "sub/./../../outside/x"])
def test_dotdot_traversal_is_denied(guard, path):
    c = guard.check(path)
    assert not c.ok and c.code == "outside_roots"


def test_absolute_path_outside_is_denied(guard, tmp_path):
    assert not guard.check(str(tmp_path / "outside" / "x")).ok
    assert not guard.check("/etc/passwd").ok and not guard.check("/").ok


def test_absolute_path_with_dotdot_back_inside_is_ok(guard, ws, tmp_path):
    assert guard.check(str(ws / ".." / "ws" / "a.txt")).ok  # normalises back into the root


def test_string_prefix_is_not_containment(ws, tmp_path):
    """/…/ws-evil starts with the string /…/ws but is a different directory."""
    evil = tmp_path / "ws-evil"
    evil.mkdir()
    g = PathGuard([ws], base_dir=ws)
    assert not g.check(str(evil / "f")).ok
    assert not g.check(str(tmp_path / "ws2")).ok
    assert g.check(str(ws / "f")).ok
    assert not is_within(str(evil), str(ws)) and is_within(str(ws), str(ws))


def test_percent_encoded_dotdot_is_just_a_name(guard, ws):
    c = guard.check("%2e%2e/%2e%2e/x")
    assert c.ok and c.resolved.startswith(str(ws))  # no URL decoding: stays a literal directory name


def test_relative_paths_use_base_dir_not_cwd(guard, ws, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path / "outside")
    c = guard.check("a.txt")
    assert c.ok and c.resolved == str(ws / "a.txt")


def test_relative_roots_resolve_against_project_dir(tmp_path, monkeypatch):
    (tmp_path / "workspace").mkdir()
    monkeypatch.chdir(tmp_path)
    g = PathGuard(["workspace"])
    assert g.allowed_roots == [str(tmp_path / "workspace")]
    assert g.check("file.txt").resolved == str(tmp_path / "workspace" / "file.txt")
    assert not g.check("../file.txt").ok


def test_tilde_expands_to_home_and_is_judged_like_any_path(ws, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "outside"))
    g = PathGuard([ws], base_dir=ws)
    assert not g.check("~/x").ok
    assert PathGuard([tmp_path / "outside"]).check("~/x").ok


# ---- symlinks ------------------------------------------------------------------------------------------------
@posix_only
def test_symlink_escaping_the_root_is_denied(guard, ws, tmp_path):
    (ws / "link").symlink_to(tmp_path / "outside", target_is_directory=True)
    c = guard.check("link/secret.txt")
    assert not c.ok and c.code == "outside_roots" and c.symlinked
    assert c.resolved == str(tmp_path / "outside" / "secret.txt")  # shown resolved, so the user sees the truth


@posix_only
def test_symlink_inside_the_root_is_allowed_and_resolved(guard, ws):
    (ws / "alias").symlink_to(ws / "sub", target_is_directory=True)
    c = guard.check("alias/a.txt")
    assert c.ok and c.symlinked and c.resolved == str(ws / "sub" / "a.txt")


@posix_only
def test_symlink_then_dotdot_is_evaluated_like_the_os_does(guard, ws, tmp_path):
    """link -> outside/deep ; 'link/../x' must be outside/x (OS semantics), NOT ws/x (lexical collapse)."""
    (tmp_path / "outside" / "deep").mkdir()
    (ws / "link").symlink_to(tmp_path / "outside" / "deep", target_is_directory=True)
    c = guard.check("link/../x")
    assert not c.ok and c.resolved == str(tmp_path / "outside" / "x")


@posix_only
def test_dangling_symlink_pointing_outside_is_denied(guard, ws, tmp_path):
    (ws / "dangling").symlink_to(tmp_path / "outside" / "does-not-exist")
    assert not guard.check("dangling").ok


@posix_only
def test_file_symlink_to_outside_file_is_denied(guard, ws, tmp_path):
    target = tmp_path / "outside" / "passwd"
    target.write_text("x")
    (ws / "innocent.txt").symlink_to(target)
    assert not guard.check("innocent.txt").ok


@posix_only
def test_symlink_loop_never_raises_uncontrolled(guard, ws):
    (ws / "a").symlink_to(ws / "b")
    (ws / "b").symlink_to(ws / "a")
    try:
        c = guard.check("a")
        assert c.ok in (True, False)
    except InvalidRequestError:
        pass  # a controlled error is just as acceptable


@posix_only
def test_symlinked_root_is_resolved(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "rootlink").symlink_to(real, target_is_directory=True)
    g = PathGuard([tmp_path / "rootlink"])
    assert g.check(str(real / "a")).ok and g.check(str(tmp_path / "rootlink" / "a")).ok


# ---- allow-list / deny-list semantics ----------------------------------------------------------------------------
def test_no_roots_denies_everything(tmp_path):
    g = PathGuard([])
    c = g.check(str(tmp_path / "x"))
    assert not c.ok and c.code == "no_roots"


def test_filesystem_root_is_never_an_allowed_root():
    with pytest.raises(PolicyError, match="filesystem root"):
        PathGuard(["/"])
    with pytest.raises(PolicyError):
        PathGuard(["/../.."])


def test_denied_paths_beat_allowed_roots(ws):
    (ws / "private").mkdir()
    g = PathGuard([ws], denied_paths=[ws / "private"], base_dir=ws)
    assert not g.check("private/x").ok and g.check("private/x").code == "denied_path"
    assert not g.check("sub/../private/x").ok  # also via equivalent spelling
    assert g.check("public/x").ok


def test_protected_paths_block_modification_only(ws):
    (ws / "audit.jsonl").write_text("")
    g = PathGuard([ws], protected_paths=[ws / "audit.jsonl"], base_dir=ws)
    assert g.check("audit.jsonl").ok  # reading is fine
    c = g.check("audit.jsonl", modifying=True)
    assert not c.ok and c.code == "protected_path"


def test_several_roots(ws, tmp_path):
    other = tmp_path / "outside"
    g = PathGuard([ws, other], base_dir=ws)
    assert g.check(str(other / "x")).ok and g.check("a").ok and not g.check("/etc/hosts").ok


# ---- malformed input -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["", "   ", None, 5, "a\x00b", "a\nb", "a\x7fb", "x" * 5000, b"bytes"])
def test_malformed_paths_raise_a_controlled_error(guard, bad):
    with pytest.raises(InvalidRequestError):
        guard.check(bad)


def test_rule_path_patterns_are_validated(guard):
    with pytest.raises(PolicyError):
        guard.resolve_pattern("")
    with pytest.raises(PolicyError):
        guard.resolve_pattern("a\x00b")


# ---- hosts ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,host", [
    ("docs.python.org", "docs.python.org"), ("HTTPS://Docs.Python.org:443/x?y#z", "docs.python.org"),
    ("example.com.", "example.com"), ("http://[::1]:8080/", "::1"), ("127.0.0.1", "127.0.0.1"),
    ("bücher.example", "xn--bcher-kva.example"), ("  Example.COM  ", "example.com"),
])
def test_normalize_host(raw, host):
    assert normalize_host(raw) == host


@pytest.mark.parametrize("bad", ["", "  ", None, "a b", "http://user:pw@host/", "http:///x", "a..b", "-bad.com",
                                 "bad-.com", "host/path", "a@b", "x" * 300 + ".com", "ex\x00ample.com", "a\\b"])
def test_normalize_host_rejects_garbage(bad):
    with pytest.raises(InvalidRequestError):
        normalize_host(bad)


def test_host_matching():
    assert host_matches("example.com", "example.com") and not host_matches("example.com", "api.example.com")
    assert host_matches("*.example.com", "api.example.com") and host_matches("*.example.com", "a.b.example.com")
    assert not host_matches("*.example.com", "example.com")  # apex is not a subdomain
    assert not host_matches("*.example.com", "evil-example.com")
    assert not host_matches("*.example.com", "example.com.evil.org")
    assert not host_matches("example.com", "example.com.evil.org")
