# Entscheidungsvorlage: historischer UIA-Bereichswächter

Gegenstand: `tests/test_computer_uia_tools.py::test_the_ui_tool_only_touches_computer_and_documentation_files` (eingeführt mit #66, Commit `c239b81`). **Unverändert.** Diese Vorlage ändert nichts am Wächter; die Zusatzdateien sind rein additiv.

## 1. Ursprünglicher Zweck
Die damalige UI-Tool-Arbeit sollte beweisen, dass sie nur über die vorhandene `build_computer`-Fabrik verdrahtet wurde und **nicht** `bootstrap.py`, `permissions/`, `config/`, `.github/`, `.claude/`, `CLAUDE.md`, `pyproject.toml` oder die Sicherheitstests (`tests/test_security_*`, `test_emergency_stop.py`, `test_autonomy_invariants.py`) berührte. Dazu vergleicht er `git diff --name-only origin/main...HEAD` mit dieser Verbotsliste. Die Änderung `c239b81` selbst berührt nur `README.md`, `docs/TESTING.md`, fünf Dateien in `src/jarvis/computer/` und zwei Tests – die Regel war für sie erfüllt.

## 2. Tatsächliches Verhalten heute
- Der Test hängt vom Checkout ab: ohne `origin/main` (flacher CI-Checkout) **überspringt** er; mit `origin/main` vergleicht er die *gesamte* Differenz zum aktuellen `main`.
- **Schon die V2.0-Basis `7c2b4b7` ist dagegen rot**, sobald `origin/main` vorliegt: `bootstrap.py` unterscheidet sich dort von `main` um 63 Zeilen (6 Commits). Der Wächter prüft also faktisch nicht mehr „die UI-Tool-Arbeit“, sondern „jede Arbeit seit `main`“. Das ist kein V2.1-Befund, V2.1 macht ihn nur sichtbar.
- Die Änderung von V2.1 an `bootstrap.py` (`git diff 7c2b4b7 claude/v21-integration -- src/jarvis/bootstrap.py`): 9 Zeilen hinzu, 3 geändert – Funktion `emergency_guard(core)`, `speech_guard` delegiert dorthin, und das Schlüsselwort `stop_guard=emergency_guard(core)` an `build_agents`. Nichts sonst.

## 3. Sicherheitsgarantien der Zusatzprüfung (`tests/test_v21_bootstrap_wiring.py`)
1. **Strukturgleichheit:** Fingerabdruck über alle Funktionen, Aufrufe (Name und Schlüsselwörter), Textkonstanten, Importe und Definitionen von `bootstrap.py` – ausgenommen `emergency_guard`, `speech_guard` und das Schlüsselwort `stop_guard` – gleich dem Stand `7c2b4b7`. Jede zusätzliche Verdrahtung, jeder neue Import, jede geänderte Konstante (z. B. `"deny"`) macht ihn rot.
2. **Guard rein lesend:** keine Aufrufe, nur `permissions.emergency.engaged/reason`.
3. **Bindung:** `stop_guard` genau einmal, nur an `build_agents`, nur als `emergency_guard(core)`.
4. **N3-B** (`check_bootstrap`): weiter erfüllt – `PermissionEngine` nur über `build_permission_engine`, Not-Aus wird nur registriert, nie ausgelöst/aufgehoben, Bestätigungsanbieter nur unter `!= "deny"`.
5. **N3-D:** `permissions/`, `config/jarvis.toml` und die Sicherheitstests sind hash-gesichert (`test_protected_files.py`) – dort ersetzt das Manifest genau den Teil des historischen Wächters, der diese Dateien betraf.
Negativtests (neun Mutationen: zusätzlicher Aufruf, Guard löst den Latch aus, Guard liest Weiteres, Guard fehlt, `stop_guard=None`, zweites `stop_guard`, neuer Import, abgeschwächte Bestätigungsbedingung, umbenannte Funktion) sind rot, wenn die Prüfung versagt.

## 4. Vorschlag (nicht angewendet)
Die Verbotsliste des historischen Tests bleibt wörtlich erhalten. Nur für `src/jarvis/bootstrap.py` gilt zusätzlich: *erlaubt, wenn `wiring_problems(bootstrap.py) == []`*. Als Code (nur Funktion, `tests/test_v21_uia_guard_proposal.py`):

```python
forbidden = historic_guard(changed)                       # unverändert
if "src/jarvis/bootstrap.py" in forbidden and wiring_problems(bootstrap_source) == []:
    forbidden.remove("src/jarvis/bootstrap.py")           # nur die lesende Guard-Verdrahtung
```
Negativtests (grün, d. h. der Vorschlag bleibt streng): alle anderen geschützten Pfade (`permissions/`, `.github/`, `.claude/`, `config/`, `CLAUDE.md`, `pyproject.toml`, Sicherheits- und Not-Aus-Tests) bleiben auch zusammen mit einer sauberen `bootstrap.py` verboten; vier Mutationen der `bootstrap.py` bleiben verboten; die Ursprungsänderung `c239b81` ist unter alter und neuer Regel sauber.

## 5. Optionen
| | Option | Wirkung | Risiko |
|---|---|---|---|
| A | Wächter unverändert lassen | bleibt in Checkouts mit `origin/main` rot (auch auf V2.0-Basis); in CI übersprungen | dauerhaft rotes Signal, Gewöhnung an Rot |
| **B (Empfehlung)** | Wächter wie in 4 anpassen | Zweck bleibt vollständig erhalten, `bootstrap.py` nur für die geprüfte Guard-Verdrahtung | Anpassung eines Wächters – deshalb nur mit Ihrer Freigabe |
| C | Wächter auf die feste Dateiliste von `c239b81` begrenzen | trivial wahr; Schutz fällt komplett an Manifest/AST/Fingerabdruck | verliert die laufende Prüfung der Differenz zu `main` |

## 6. Auswirkung auf Sicherheitsgrenzen
Keine: Berechtigungsengine, Not-Aus, X0, Konfiguration und die Sicherheitstests sind weder verändert noch von der Anpassung betroffen. **Freigabe nötig für B oder C.**

---

## 7. Nachtrag: Prüfung von Option B (Branch `claude/v21-uia-guard-b`, nicht im Integrationsbranch)

**Befund bei der Prüfung:** Die in Abschnitt 3 beschriebene Zusatzprüfung war **schwächer** als das ursprüngliche „keine Änderung an `bootstrap.py`“: der damalige Fingerabdruck erfasste nur Aufrufnamen, Textkonstanten, Importe und Definitionen. Eine umgedrehte Bedingung (`is not` → `is`), vertauschte Argumente oder `ToolRegistry(permissions or None)` wären unentdeckt geblieben. Für Option B reichte das nicht.

**Korrektur (red-first, 7 zuvor nicht gefundene Mutationen):** `fingerprint` bildet jetzt den **vollständigen kanonischen AST** ab (Knotenarten, alle Felder, Operatoren, Namen, Konstanten, Docstrings, Reihenfolge; nur Kommentare/Formatierung sind frei; eigenes Format, kein `ast.dump`, leere Felder ausgelassen → unabhängig von der Python-Version). Ausgenommen sind nur `emergency_guard`, `speech_guard` und das Schlüsselwort `stop_guard`; **diese drei Teile sind einzeln auf ihre exakte Form gepinnt** (`EMERGENCY_GUARD_SHAPE`, `SPEECH_GUARD_SHAPE`, Bindung genau einmal an `build_agents` als `emergency_guard(core)`).

**Änderung am historischen Test (exakt vier Zeilen, Verbotsliste und alle übrigen Zeilen unverändert, kein Skip hinzugefügt):**
```diff
@@ def test_the_ui_tool_only_touches_computer_and_documentation_files():
     forbidden = [f for f in changed if ... bootstrap.py ... ]
+    if "src/jarvis/bootstrap.py" in forbidden:      # V2.1 (Option B): ...
+        from test_v21_bootstrap_wiring import SOURCE, wiring_problems     # fehlt die Pruefung, schlaegt der Test fehl (kein Skip)
+        if wiring_problems(SOURCE.read_text(encoding="utf-8")) == []:
+            forbidden.remove("src/jarvis/bootstrap.py")
     assert forbidden == [], forbidden
```

**Gegenbeweis am echten, angepassten Test** (jede Mutation einzeln committet gegen `origin/main`, Wegwerf-Worktree): unverändert → grün; bootstrap-Bedingung gedreht, Argument erweitert, `speech_guard` delegiert nicht, `emergency.py`, `engine.py`, `config/jarvis.toml`, neues `.github/`, `tests/test_emergency_stop.py`, `pyproject.toml` → **jeweils rot**.

**Was Option B ausdrücklich NICHT zeigt / Grenzen (ehrlich):**
1. Die Basis der Prüfung ist der **geprüfte V2.0-Stand `7c2b4b7`**. Die 63 Zeilen, um die `bootstrap.py` dort von `main` abweicht, werden **nicht neu bewertet**, sondern als Baseline akzeptiert (sie sind Teil der V2.0-Abnahme). Gegenüber der V2.0-Basis ist die Prüfung strenger als der historische Test (jede Abweichung wird gefunden); gegenüber `main` ist die V2.0-Differenz vertraut.
2. Wer `BASELINE_7C2B4B7` oder die Form-Pins im Testfile ändert, kann die Prüfung selbst aufweichen. Empfehlung (Besitzeraktion, `protected_manifest.json` ist geschützt): `tests/test_v21_bootstrap_wiring.py` und `tests/test_computer_uia_tools.py` in das Hash-Manifest N3-D aufnehmen, damit diese Änderung nur gemeinsam mit einem Manifestwechsel möglich ist.
3. Option B ändert weder `PermissionEngine` noch Not-Aus noch X0.
