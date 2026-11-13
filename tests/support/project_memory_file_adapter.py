"""TESTADAPTER (nicht produktiv, nirgends verdrahtet): Dateiablage fuer `ProjectMemory`, nur um das Speicherformat-Konzept (docs/v21/M3_PERSISTENZ.md) pruefbar zu machen.

Format: ein Verzeichnis, je Projekt EINE Datei `<projekt>.json` = {"format": 1, "project": ..., "saved_at": ..., "records": [...], "mac": hex} (HMAC-SHA256 ueber den kanonischen Rest, Schluessel wird
uebergeben, nie gespeichert). Schreiben atomar (Temp-Datei im selben Verzeichnis, fsync, os.replace): ein Abbruch laesst die alte Datei unberuehrt. Laden prueft MAC, Projektname und
Schema (ueber `ProjectMemory.from_dict`, das Geheimnisse und Schema erneut prueft); ein beschaedigtes Projekt wird in Quarantaene gemeldet, die anderen werden geladen."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.memory.project_memory import VERSION, ProjectMemory

FORMAT = 1
_NAME = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")


def _mac(key: bytes, body: dict[str, Any]) -> str:
    return hmac.new(key, json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), hashlib.sha256).hexdigest()


class FileAdapter:
    def __init__(self, directory: Path, key: bytes) -> None:
        if len(key) < 16:
            raise ValueError("key too short")
        self.dir, self._key = Path(directory), key

    def _path(self, project: str) -> Path:
        if not _NAME.match(project):
            raise ValueError("invalid project name")
        return self.dir / f"{project}.json"

    def save_project(self, memory: ProjectMemory, project: str, now: datetime, *, crash_before_replace: bool = False) -> None:
        snap = memory.to_dict()["projects"].get(project)
        if snap is None:
            raise KeyError("no such project")
        body = {"format": FORMAT, "version": VERSION, "project": project, "saved_at": now.isoformat(), "records": snap}
        doc = {**body, "mac": _mac(self._key, body)}
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f".{project}.json.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        if crash_before_replace:                         # Testhaken: der Prozess bricht zwischen Schreiben und Austausch ab
            raise KeyboardInterrupt("simulated abort")
        os.replace(tmp, self._path(project))

    def save_all(self, memory: ProjectMemory, now: datetime) -> None:
        for project in memory.projects():
            self.save_project(memory, project, now)

    def load(self, **kw: Any) -> tuple[ProjectMemory, list[str]]:
        """-> (Gedaechtnis aus allen intakten Projekten, Liste der unlesbaren Projekte). Temp-Reste werden ignoriert und nie gelesen."""
        merged: dict[str, Any] = {"version": VERSION, "projects": {}}
        bad: list[str] = []
        for path in sorted(self.dir.glob("*.json")) if self.dir.exists() else []:
            name = path.stem
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                mac = doc.pop("mac")
                if not isinstance(doc, dict) or not hmac.compare_digest(mac, _mac(self._key, doc)) or doc.get("project") != name or doc.get("format") != FORMAT:
                    raise ValueError("integrity")
                ProjectMemory.from_dict({"version": VERSION, "projects": {name: doc["records"]}}, **kw)      # Schema und Geheimnisse erneut pruefen
                merged["projects"][name] = doc["records"]
            except Exception:  # noqa: BLE001 - ein defektes Projekt darf die anderen nicht verhindern
                bad.append(name)
        return ProjectMemory.from_dict(merged, **kw), bad

    def delete_project(self, project: str) -> bool:
        p = self._path(project)
        if p.exists():
            p.unlink()
            return True
        return False
