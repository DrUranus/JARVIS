"""PathGuard on Windows: junctions and other reparse points that lead OUT of an allowed directory.

The POSIX symlink tests of tests/test_security_paths.py are skipped on Windows ("POSIX symlink semantics"), so until now nothing tested how the central path check treats NTFS
reparse points there. Junctions (mount points) need no privilege and are created with the standard-library helper `_winapi.CreateJunction`; real symbolic links need the
"create symbolic links" privilege or Developer Mode and are skipped with an explicit reason when the account lacks it.

The security contract of PathGuard is: if `check()` says ok, the path in `PathCheck.resolved` lies inside an allowed root AND is what the operating system would open for the
raw path. Both halves are asserted. Nothing is deleted outside pytest's tmp_path; junction removal uses os.rmdir on the link itself (never the target).
A FAILING test here is a finding about PathGuard on Windows, not a test problem - it records the Python version for exactly that reason."""
from __future__ import annotations

import os
import sys

import pytest

from jarvis.permissions import PathGuard

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="NTFS junctions / reparse points exist only on Windows (the POSIX symlink tests cover the other platforms)")

PY = sys.version.split()[0]


def junction(link, target):
    import _winapi                                                      # Windows-only private module, used by CPython's own tests for this purpose
    _winapi.CreateJunction(str(target), str(link))


def same_file(a, b) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


@pytest.fixture
def world(tmp_path):
    ws = tmp_path / "ws"
    (ws / "sub").mkdir(parents=True)
    (ws / "sub" / "a.txt").write_text("inside")
    outside = tmp_path / "outside"
    (outside / "private").mkdir(parents=True)
    (outside / "secret.txt").write_text("secret")
    (outside / "private" / "f.txt").write_text("private")
    return tmp_path, ws, outside


def assert_contract(guard: PathGuard, raw: str, ws, *, modifying: bool = False):
    """If the check passes, the resolved path is inside the root and designates the same file the OS opens for the raw path."""
    c = guard.check(raw, modifying=modifying)
    if c.ok:
        assert os.path.normcase(c.resolved).startswith(os.path.normcase(str(ws.resolve()))), (PY, raw, c)
        if os.path.exists(raw):
            assert same_file(raw, c.resolved), f"PathGuard resolved {raw!r} to {c.resolved!r}, but the OS opens a different file (python {PY})"
    return c


def test_junction_out_of_the_root_is_denied(world):
    tmp, ws, outside = world
    junction(ws / "jun", outside)
    g = PathGuard([ws], base_dir=ws)
    for raw in (str(ws / "jun" / "secret.txt"), "jun\\secret.txt", "jun/secret.txt", str(ws / "jun")):
        c = assert_contract(g, raw, ws)
        assert not c.ok and c.code == "outside_roots" and c.symlinked, (PY, raw, c)
        assert os.path.normcase(c.resolved).startswith(os.path.normcase(str(outside.resolve()))), c


def test_junction_inside_the_root_is_allowed_and_resolved(world):
    tmp, ws, outside = world
    junction(ws / "alias", ws / "sub")
    g = PathGuard([ws], base_dir=ws)
    c = assert_contract(g, str(ws / "alias" / "a.txt"), ws)
    assert c.ok and c.symlinked and os.path.normcase(c.resolved) == os.path.normcase(str(ws.resolve() / "sub" / "a.txt")), (PY, c)


def test_chain_of_junctions_that_ends_outside_is_denied(world):
    tmp, ws, outside = world
    junction(ws / "j2", outside)
    junction(ws / "j1", ws / "j2")                                     # j1 -> j2 -> outside
    c = assert_contract(PathGuard([ws], base_dir=ws), str(ws / "j1" / "secret.txt"), ws)
    assert not c.ok and c.code == "outside_roots", (PY, c)


def test_junction_created_after_the_guard_exists_is_still_caught(world):
    tmp, ws, outside = world
    g = PathGuard([ws], base_dir=ws)
    assert g.check("new\\file.txt").ok                                 # the name does not exist yet: judged inside
    junction(ws / "new", outside)                                      # now the same name leads out
    c = assert_contract(g, "new\\secret.txt", ws)
    assert not c.ok and c.code == "outside_roots", (PY, c)


@pytest.mark.parametrize("raw", ["jun\\..\\x.txt", "jun\\..\\..\\outside\\secret.txt", "jun\\sub\\..\\..\\secret.txt", "jun/../../outside/secret.txt", ".\\jun\\.\\secret.txt"])
def test_dotdot_around_a_junction_never_lets_the_guard_and_the_os_disagree(world, raw):
    """Win32 normalises '..' lexically while POSIX follows the link first; whichever Python's realpath does, the contract must hold."""
    tmp, ws, outside = world
    junction(ws / "jun", outside)
    (ws / "x.txt").write_text("x")
    assert_contract(PathGuard([ws], base_dir=ws), raw, ws)


@pytest.mark.parametrize("raw", ["jun.\\secret.txt", "jun \\secret.txt", "jun\\secret.txt:stream", "JUN\\SECRET.TXT", "jun\\.\\secret.txt", "\\\\?\\{ws}\\jun\\secret.txt"])
def test_alternative_spellings_of_a_path_through_a_junction(world, raw):
    tmp, ws, outside = world
    junction(ws / "jun", outside)
    raw = raw.replace("{ws}", str(ws))
    c = assert_contract(PathGuard([ws], base_dir=ws), raw, ws)
    assert not c.ok, (PY, raw, c)


def test_short_8_3_name_of_the_junction_target_is_resolved_to_the_long_name(world):
    tmp, ws, outside = world
    import ctypes
    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(outside), buf, len(buf))
    if not n or buf.value.lower() == str(outside).lower():
        pytest.skip("8.3 short names are disabled on this volume (nothing to test)")
    junction(ws / "jun", buf.value)
    c = assert_contract(PathGuard([ws], base_dir=ws), str(ws / "jun" / "secret.txt"), ws)
    assert not c.ok and c.code == "outside_roots", (PY, c)


def test_denied_path_is_still_denied_when_reached_through_a_junction(world):
    tmp, ws, outside = world
    junction(ws / "jun", outside)
    g = PathGuard([ws, outside], denied_paths=[outside / "private"], base_dir=ws)
    c = assert_contract(g, str(ws / "jun" / "private" / "f.txt"), ws)
    assert not c.ok and c.code == "denied_path", (PY, c)


def test_protected_path_can_not_be_modified_through_a_junction_alias(world):
    tmp, ws, outside = world
    (ws / "audit").mkdir()
    (ws / "audit" / "audit.jsonl").write_text("{}")
    junction(ws / "alias", ws / "audit")
    g = PathGuard([ws], protected_paths=[ws / "audit"], base_dir=ws)
    assert g.check(str(ws / "alias" / "audit.jsonl")).ok                                   # reading is fine
    c = g.check(str(ws / "alias" / "audit.jsonl"), modifying=True)
    assert not c.ok and c.code == "protected_path", (PY, c)


def test_an_allowed_root_that_is_itself_a_junction_is_resolved_to_its_target(world):
    tmp, ws, outside = world
    junction(tmp / "rootlink", ws)
    g = PathGuard([tmp / "rootlink"], base_dir=tmp / "rootlink")
    assert os.path.normcase(g.allowed_roots[0]) == os.path.normcase(str(ws.resolve()))
    assert g.check("sub\\a.txt").ok and g.check(str(ws / "sub" / "a.txt")).ok            # through the link and through the real path
    assert not g.check(str(outside / "secret.txt")).ok


def test_dangling_junction_to_an_outside_directory_that_appears_later_is_denied(world):
    """Create a junction to a directory that does not exist yet, check, THEN create the target: the junction must never have been judged 'inside'. A failure here would be a
    real PathGuard weakness (a tool could be steered out of the root by creating the target afterwards)."""
    tmp, ws, outside = world
    ghost = tmp / "ghost"
    ghost.mkdir()
    junction(ws / "dang", ghost)
    os.rmdir(ghost)                                                                          # now dangling
    g = PathGuard([ws], base_dir=ws)
    c = g.check("dang\\x.txt")
    assert not c.ok, f"a dangling junction to {ghost} was judged inside the root (python {PY}): {c}"
    ghost.mkdir()                                                                            # the target appears afterwards
    (ghost / "x.txt").write_text("outside")
    c2 = assert_contract(g, "dang\\x.txt", ws)
    assert not c2.ok and c2.code == "outside_roots", (PY, c2)


def test_directory_symlink_out_of_the_root_is_denied_when_the_account_may_create_one(world):
    tmp, ws, outside = world
    try:
        os.symlink(outside, ws / "slink", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"this account may not create symbolic links (WinError {getattr(exc, 'winerror', '?')}); the junction tests above cover the privilege-free case")
    c = assert_contract(PathGuard([ws], base_dir=ws), str(ws / "slink" / "secret.txt"), ws)
    assert not c.ok and c.code == "outside_roots" and c.symlinked, (PY, c)


def test_file_symlink_to_an_outside_file_is_denied_when_the_account_may_create_one(world):
    tmp, ws, outside = world
    try:
        os.symlink(outside / "secret.txt", ws / "innocent.txt")
    except OSError as exc:
        pytest.skip(f"this account may not create symbolic links (WinError {getattr(exc, 'winerror', '?')})")
    c = assert_contract(PathGuard([ws], base_dir=ws), str(ws / "innocent.txt"), ws)
    assert not c.ok and c.code == "outside_roots", (PY, c)


def test_removing_a_junction_does_not_touch_the_target(world):
    """Safety of the tests themselves: os.rmdir on the link removes only the link."""
    tmp, ws, outside = world
    junction(ws / "jun", outside)
    os.rmdir(ws / "jun")
    assert (outside / "secret.txt").read_text() == "secret"
