"""Where the proposal store really lives: the absolute data directory is reported, a relative setting is flagged, and OneDrive folders produce a warning (never an error and
never a silent move). The default `data_dir` is deliberately NOT changed: a relative value is resolved against the working directory, there is no migration code, so
changing the default would make existing data silently invisible."""
from __future__ import annotations

import os
from pathlib import Path

from jarvis.config import SelfImprovementSettings
from jarvis.self_improvement.factory import build_self_improvement, cloud_sync_warning
from test_self_improvement_store import settings_for


def test_the_default_data_dir_is_unchanged_and_relative():
    assert SelfImprovementSettings().data_dir == "data/improvements" and not Path(SelfImprovementSettings().data_dir).is_absolute()


def test_onedrive_folder_named_by_the_environment_is_flagged(tmp_path):
    od = tmp_path / "OneDrive"
    (od / "Dokumente").mkdir(parents=True)
    w = cloud_sync_warning(od / "Dokumente" / "improve", {"OneDrive": str(od)})
    assert "inside the OneDrive folder" in w and "prefer a folder outside OneDrive" in w
    assert cloud_sync_warning(tmp_path / "local", {"OneDrive": str(od)}) == ""


def test_onedrive_by_folder_name_is_flagged_even_without_the_environment(tmp_path):
    p = tmp_path / "OneDrive - Contoso" / "x"
    p.mkdir(parents=True)
    assert "looks like it is inside a OneDrive folder" in cloud_sync_warning(p / "improve", {})
    assert cloud_sync_warning(tmp_path / "elsewhere", {}) == ""


def test_the_factory_reports_the_absolute_directory_and_warns_about_a_relative_one(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = settings_for(tmp_path, JARVIS_SELF_IMPROVEMENT_DATA_DIR="rel_improve", JARVIS_SELF_IMPROVEMENT_KEY_PATH=tmp_path / "keys" / "k")
    sub = build_self_improvement(s, env={})
    assert sub.available and sub.data_dir == str((tmp_path / "rel_improve").resolve())
    assert "relative" in sub.warning and sub.data_dir in sub.warning and sub.describe()["data_dir"] == sub.data_dir


def test_an_absolute_directory_outside_onedrive_has_no_warning(tmp_path):
    sub = build_self_improvement(settings_for(tmp_path), env={})
    assert sub.available and sub.warning == "" and os.path.isabs(sub.data_dir)


def test_a_onedrive_data_dir_still_works_but_is_flagged(tmp_path):
    od = tmp_path / "OneDrive"
    od.mkdir()
    s = settings_for(tmp_path, JARVIS_SELF_IMPROVEMENT_DATA_DIR=od / "improve", JARVIS_SELF_IMPROVEMENT_KEY_PATH=tmp_path / "keys" / "k")
    sub = build_self_improvement(s, env={"OneDrive": str(od)})
    assert sub.available and "OneDrive" in sub.warning
    sub.manager.propose("t", "p")
    assert (od / "improve" / "proposals.json").exists()               # the data is where it was configured: nothing was moved
