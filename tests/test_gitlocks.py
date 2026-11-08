"""Git-Sperrdateien: sichere Diagnose, Entfernen nur verwaister Sperren nach Prozesspruefung. Nur Dateisystem im tmp_path, keine echten Prozesse, kein Netzwerk."""
import os
import sys
import time
from pathlib import Path

import pytest

from jarvis.interface import gitlocks as G


def make_repo(tmp_path, locks=("index.lock",), age=600):
    git = tmp_path / "repo" / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    out = []
    for name in locks:
        f = git / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("")
        t = time.time() - age
        os.utime(f, (t, t))
        out.append(f)
    return git, out


def test_find_git_dir_walks_up_and_follows_gitdir_files(tmp_path):
    git, _ = make_repo(tmp_path)
    sub = tmp_path / "repo" / "a" / "b"
    sub.mkdir(parents=True)
    assert G.find_git_dir(sub) == git.resolve()
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {git}\n")
    assert G.find_git_dir(wt) == git.resolve()


def test_scan_finds_locks_but_not_other_files_or_pack_dirs(tmp_path):
    git, _ = make_repo(tmp_path, ("index.lock", "refs/heads/main.lock", "objects/pack/x.lock"))
    (git / "config").write_text("x")
    names = {l.path.name for l in G.scan(git)}
    assert names == {"index.lock", "main.lock"}


def test_verdicts_cover_active_unknown_young_orphan_and_unsafe(tmp_path):
    git, [f] = make_repo(tmp_path, age=600)
    lock = G.scan(git)[0]
    assert G.judge([lock], ["git.exe"])[0].state == "active"
    assert G.judge([lock], None)[0].state == "unknown"
    assert G.judge([lock], [], min_age=3600)[0].state == "young"
    assert G.judge([lock], [])[0].state == "orphan"
    big = tmp_path / "repo" / ".git" / "big.lock"
    big.write_text("x" * 5000)
    assert [v.state for v in G.judge([l for l in G.scan(git) if l.path == big], [])] == ["unsafe"]


def test_a_directory_or_symlink_named_lock_is_never_removable(tmp_path):
    git, _ = make_repo(tmp_path, ())
    (git / "dir.lock").mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("keep")
    link = git / "link.lock"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks nicht verfuegbar (nicht bestanden, nur uebersprungen)")
    t = time.time() - 9999
    os.utime(link, (t, t), follow_symlinks=False)
    assert G.remove_orphans(git, 1, procs_fn=lambda: []) == []
    assert target.read_text() == "keep" and (git / "dir.lock").is_dir()


def test_remove_needs_orphan_state_and_rechecks_processes_right_before_deleting(tmp_path):
    git, [f] = make_repo(tmp_path, age=600)
    assert G.remove_orphans(git, procs_fn=lambda: ["git.exe"]) == [] and f.exists()          # Git laeuft: nichts entfernt
    assert G.remove_orphans(git, procs_fn=lambda: None) == [] and f.exists()                 # Liste unlesbar: nichts entfernt
    calls = iter([[], ["git.exe"]])                                                           # beim zweiten Pruefen taucht ein Git-Prozess auf
    assert G.remove_orphans(git, procs_fn=lambda: next(calls)) == [] and f.exists()
    assert G.remove_orphans(git, procs_fn=lambda: []) == [f] and not f.exists()               # nur dann: entfernt


def test_young_locks_survive(tmp_path):
    git, [f] = make_repo(tmp_path, age=5)
    assert G.remove_orphans(git, procs_fn=lambda: []) == [] and f.exists()


def test_cli_is_read_only_by_default_and_needs_yes(tmp_path, monkeypatch, capsys):
    git, [f] = make_repo(tmp_path, age=600)
    monkeypatch.setattr(G, "git_processes", lambda *a, **k: [])
    assert G.main([str(tmp_path / "repo")]) == 0 and f.exists()
    out = capsys.readouterr().out
    assert "ORPHAN" in out and "nur lesend" in out
    assert G.main([str(tmp_path / "repo"), "--remove"]) == 1 and f.exists()                   # ohne --yes nichts
    assert G.main([str(tmp_path / "repo"), "--remove", "--yes"]) == 0 and not f.exists()
    assert G.main([str(tmp_path / "no-repo-here-xyz")]) in (0, 2)


def test_process_listing_failure_is_unknown_not_empty():
    def boom(*a, **k):
        raise OSError("tasklist fehlt")
    assert G.git_processes("win32", run=boom) is None
    class CP:
        returncode, stdout = 0, '"git.exe","123","Console","1","10 K"\r\n"explorer.exe","1","Console","1","1 K"\r\n"git-remote-https.exe","2","Console","1","1 K"\r\n'
    assert G.git_processes("win32", run=lambda *a, **k: CP()) == ["git-remote-https.exe", "git.exe"]
    assert G.git_processes("linux", proc_root="/nonexistent-proc") is None


def test_onedrive_hint_and_module_never_kills_processes():
    assert G.in_onedrive(Path(r"C:\Users\x\OneDrive\Dokumente\JARVIS\.git")) and not G.in_onedrive(Path(r"C:\dev\JARVIS\.git"), env={})
    src = Path(G.__file__).read_text(encoding="utf-8")
    assert "taskkill" not in src and ".kill(" not in src and "terminate(" not in src and "rmtree" not in src
