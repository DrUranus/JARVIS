"""UI-Automation-Modell (Backlog-Schritt uia-model-fake): Datenmodell des UI-Baums, rein lesende Provider-Schnittstelle und ein deterministischer Fake-Provider.

Nur Modell und Fake: keine Bibliothek, kein Windows-Code, keine Tools, keine Aktionen, kein Netzwerk. Passwortfelder liefern nie einen Wert; Tiefe, Knotenzahl
und Textlaenge sind hart begrenzt. Laeuft unter Linux und Windows gleich."""
from __future__ import annotations

import dataclasses
import json
import re
import sys
from pathlib import Path

import pytest

from jarvis.computer import ComputerBackend, ComputerError, ErrorCode
from jarvis.computer.providers.fake_uia import FakeUiaProvider, login_tree, notepad_tree
from jarvis.computer.uia import (HARD_MAX_DEPTH, HARD_MAX_NODES, HARD_MAX_RESULTS, HARD_MAX_TEXT, ControlType, UiElement, UiFindResult, UiLimits, UiQuery,
                                 UiRect, UiSnapshot, UiTreeProvider, bound_tree, find_in_tree)

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "src" / "jarvis" / "computer"
SECRET = "hunter2-geheim"
NOTEPAD, LOGIN = 1001, 1002


def el(rid="0", name="n", ctype="Pane", children=(), **kw):
    return UiElement(runtime_id=rid, name=name, control_type=ctype, children=tuple(children), **kw)


def chain(depth: int) -> UiElement:
    node = el(f"d{depth}", f"tief {depth}")
    for i in range(depth - 1, -1, -1):
        node = el(f"d{i}", f"tief {i}", children=[node])
    return node


def wide(n: int) -> UiElement:
    return el("w", "breit", "Window", children=[el(f"w.{i}", f"kind {i}", "Button") for i in range(n)])


def count(e: UiElement) -> int:
    return 1 + sum(count(c) for c in e.children)


def depth_of(e: UiElement) -> int:
    return 0 if not e.children else 1 + max(depth_of(c) for c in e.children)


def flat(e: UiElement):
    yield e
    for c in e.children:
        yield from flat(c)


def dump(obj) -> str:
    return json.dumps(obj, default=lambda o: o.info() if hasattr(o, "info") else repr(o), ensure_ascii=False)


# ---- Steuerelementtypen und Rechteck -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [("Button", ControlType.BUTTON), ("Edit", ControlType.EDIT), ("MenuItem", ControlType.MENU_ITEM), ("menu item", ControlType.MENU_ITEM),
                                          ("  window ", ControlType.WINDOW), ("StatusBar", ControlType.STATUS_BAR), ("Thumb", ControlType.THUMB),
                                          ("gibt es nicht", ControlType.UNKNOWN), ("", ControlType.UNKNOWN), (None, ControlType.UNKNOWN), (5, ControlType.UNKNOWN)])
def test_control_types_are_parsed_leniently_and_unknown_types_never_raise(raw, expected):
    assert ControlType.from_name(raw) is expected


def test_the_control_types_seen_on_a_real_notepad_window_exist():
    for name in ("Window", "Pane", "Button", "Edit", "MenuBar", "MenuItem", "ScrollBar", "StatusBar", "Text", "Thumb", "Document"):
        assert ControlType.from_name(name) is not ControlType.UNKNOWN, name


@pytest.mark.parametrize("args", [(0, 0, -1, 5), (0, 0, 5, -1), (True, 0, 5, 5), (0, 0, 5.5, 5), ("1", 0, 5, 5), (0, None, 5, 5)])
def test_rects_reject_negative_sizes_and_non_integers(args):
    with pytest.raises(ComputerError) as exc:
        UiRect(*args)
    assert exc.value.code is ErrorCode.INVALID_INPUT


def test_rect_accepts_screen_positions_below_zero_for_secondary_monitors():
    assert UiRect(-1920, -10, 100, 50).as_list() == [-1920, -10, 100, 50]


# ---- Element: Normalisierung, Passwortfelder, Unveraenderlichkeit -------------------------------------------------------------------------
def test_a_password_field_never_carries_a_value_even_if_one_is_passed_in():
    pw = el("0.1", "Password", "Edit", is_password=True, value=SECRET)
    assert pw.value is None and pw.is_password is True
    assert SECRET not in repr(pw) and SECRET not in dump(pw.info())


def test_a_normal_field_keeps_its_value_but_repr_never_shows_it():
    e = el("0.1", "Name", "Edit", value="alice")
    assert e.value == "alice" and "alice" not in repr(e)
    assert e.info()["value"] == "alice"


def test_info_of_a_password_field_has_no_value_key_at_all():
    assert "value" not in el("p", "pw", "Edit", is_password=True, value=SECRET).info()


def test_control_characters_in_texts_are_replaced_and_texts_have_an_absolute_cap():
    e = el("x", "a\nb\x00c\td", "Text", automation_id="id\r1", value="v\x07w")
    assert e.name == "a b c d" and e.automation_id == "id 1" and e.value == "v w"
    assert len(el("x", "z" * 5000).name) <= HARD_MAX_TEXT


def test_elements_are_frozen_and_children_are_a_tuple_of_elements():
    e = el("0", "w", "Window", children=[el("0.0", "c")])
    assert isinstance(e.children, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.name = "anders"                      # type: ignore[misc]
    with pytest.raises(ComputerError):
        UiElement(runtime_id="0", name="x", control_type="Pane", children=("kein Element",))      # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [{"runtime_id": ""}, {"runtime_id": 5}, {"name": 5}, {"enabled": "ja"}, {"visible": None}, {"is_password": 1}, {"rect": (0, 0, 1, 1)}, {"value": 5}])
def test_invalid_element_fields_are_rejected_with_a_controlled_error(bad):
    base = dict(runtime_id="0", name="n", control_type="Pane")
    with pytest.raises(ComputerError) as exc:
        UiElement(**{**base, **bad})
    assert exc.value.code is ErrorCode.INVALID_INPUT


def test_an_unknown_control_type_string_becomes_unknown_not_an_error():
    assert el("0", "n", "VollerUnsinn").control_type is ControlType.UNKNOWN


# ---- Grenzen -----------------------------------------------------------------------------------------------------------------------------
def test_limits_have_safe_defaults_and_hard_maxima():
    d = UiLimits()
    assert (d.max_depth, d.max_nodes, d.max_text) == (6, 200, 200)
    assert d.max_depth <= HARD_MAX_DEPTH and d.max_nodes <= HARD_MAX_NODES
    assert (HARD_MAX_DEPTH, HARD_MAX_NODES, HARD_MAX_TEXT, HARD_MAX_RESULTS) == (12, 500, 1000, 50)
    assert UiLimits(HARD_MAX_DEPTH, HARD_MAX_NODES, HARD_MAX_TEXT)


@pytest.mark.parametrize("args", [(0, 10, 10), (3, 0, 10), (3, 10, 0), (-1, 10, 10), (HARD_MAX_DEPTH + 1, 10, 10), (3, HARD_MAX_NODES + 1, 10),
                                  (3, 10, HARD_MAX_TEXT + 1), (True, 10, 10), (3.5, 10, 10), ("3", 10, 10), (3, 10, None)])
def test_limits_outside_the_hard_bounds_or_of_the_wrong_type_are_rejected(args):
    with pytest.raises(ComputerError) as exc:
        UiLimits(*args)
    assert exc.value.code is ErrorCode.INVALID_INPUT


def test_depth_is_cut_and_reported():
    tree, nodes, truncated = bound_tree(chain(10), UiLimits(max_depth=3, max_nodes=100, max_text=50))
    assert depth_of(tree) == 3 and nodes == 4 and truncated is True


def test_a_tree_within_all_limits_is_returned_unchanged_and_not_truncated():
    original = notepad_tree()
    tree, nodes, truncated = bound_tree(original, UiLimits())
    assert tree == original and nodes == count(original) and truncated is False


def test_the_node_count_is_capped_exactly_in_document_order():
    tree, nodes, truncated = bound_tree(wide(100), UiLimits(max_depth=3, max_nodes=10, max_text=50))
    assert nodes == 10 == count(tree) and truncated is True
    assert [c.runtime_id for c in tree.children] == [f"w.{i}" for i in range(9)]       # die ersten, nie eine Auswahl


def test_a_node_budget_of_one_keeps_only_the_root():
    tree, nodes, truncated = bound_tree(wide(5), UiLimits(max_depth=3, max_nodes=1, max_text=50))
    assert tree.children == () and nodes == 1 and truncated is True


def test_texts_are_shortened_to_the_limit_with_a_marker():
    tree, _, truncated = bound_tree(el("0", "x" * 300, "Edit", value="y" * 300, automation_id="a" * 300, class_name="c" * 300), UiLimits(max_text=20))
    for text in (tree.name, tree.value, tree.automation_id, tree.class_name):
        assert len(text) == 20 and text.endswith("...")
    assert truncated is True


def test_short_texts_are_untouched():
    tree, _, truncated = bound_tree(el("0", "kurz", "Edit", value="auch kurz"), UiLimits(max_text=20))
    assert (tree.name, tree.value, truncated) == ("kurz", "auch kurz", False)


def test_bounding_is_pure_deterministic_and_idempotent():
    original = chain(8)
    snapshot = repr(original)
    once = bound_tree(original, UiLimits(max_depth=4, max_nodes=50, max_text=30))
    again = bound_tree(original, UiLimits(max_depth=4, max_nodes=50, max_text=30))
    assert once == again and repr(original) == snapshot
    assert bound_tree(once[0], UiLimits(max_depth=4, max_nodes=50, max_text=30))[0] == once[0]


def test_huge_trees_stay_within_the_hard_limits():
    for big in (chain(300), wide(20000)):
        tree, nodes, truncated = bound_tree(big, UiLimits(HARD_MAX_DEPTH, HARD_MAX_NODES, HARD_MAX_TEXT))
        assert nodes == count(tree) <= HARD_MAX_NODES and depth_of(tree) <= HARD_MAX_DEPTH and truncated is True


def test_password_fields_stay_value_free_through_bounding():
    tree, _, _ = bound_tree(login_tree(), UiLimits())
    assert all(e.value is None for e in flat(tree) if e.is_password) and SECRET not in dump(tree.info())


# ---- Suche -------------------------------------------------------------------------------------------------------------------------------
def test_query_validation():
    assert UiQuery().max_results == 20
    for bad in ({"name_equals": 5}, {"name_contains": "x" * 201}, {"automation_id": b"x"}, {"control_type": "Unsinn"}, {"control_type": 5}, {"enabled": "ja"},
                {"visible": 1}, {"max_results": 0}, {"max_results": HARD_MAX_RESULTS + 1}, {"max_results": True}, {"max_results": "5"}):
        with pytest.raises(ComputerError) as exc:
            UiQuery(**bad)
        assert exc.value.code is ErrorCode.INVALID_INPUT, bad
    assert UiQuery(control_type="Edit").control_type is ControlType.EDIT and UiQuery(control_type=ControlType.EDIT).control_type is ControlType.EDIT


def test_find_filters_are_combined_with_and_and_results_come_in_document_order():
    tree = notepad_tree()
    names = lambda q: [m.name for m in find_in_tree(tree, UiQuery(**q), UiLimits()).matches]            # noqa: E731
    assert names({"control_type": "MenuItem"}) == ["File", "Edit", "Format", "View", "Help"]
    assert names({"name_contains": "ED"}) == ["Untitled - Notepad", "Edit", "Text editor"]                  # ohne Gross-/Kleinschreibung, Dokumentreihenfolge (Wurzel zuerst)
    assert names({"name_equals": "edit"}) == [] and names({"name_equals": "Edit"}) == ["Edit"]          # exakt ist exakt
    assert names({"automation_id": "15"}) == ["Text editor"]
    assert names({"control_type": "MenuItem", "name_contains": "e"}) == ["File", "Edit", "View", "Help"]
    assert names({"control_type": "Button"}) == []


def test_find_by_state_flags_and_unmatched_queries_are_empty_not_errors():
    tree = login_tree()
    q = lambda **kw: [m.name for m in find_in_tree(tree, UiQuery(**kw), UiLimits()).matches]            # noqa: E731
    assert q(control_type="CheckBox", enabled=False) == ["Remember me"] and q(control_type="CheckBox", enabled=True) == []
    assert q(visible=False) == ["Hidden hint"]
    assert q(name_contains="gibt es nicht") == []


def test_find_returns_flat_matches_without_children_and_marks_overflow():
    result = find_in_tree(wide(30), UiQuery(control_type="Button", max_results=5), UiLimits())
    assert len(result.matches) == 5 and result.truncated is True and all(m.children == () for m in result.matches)
    all_of_them = find_in_tree(wide(30), UiQuery(control_type="Button", max_results=50), UiLimits())
    assert len(all_of_them.matches) == 30 and all_of_them.truncated is False


def test_find_searches_only_the_bounded_tree():
    result = find_in_tree(wide(100), UiQuery(control_type="Button", max_results=50), UiLimits(max_depth=3, max_nodes=10, max_text=50))
    assert len(result.matches) == 9 and result.truncated is True               # die Obergrenze der Knoten gilt auch fuer die Suche


def test_find_reports_a_password_field_but_never_its_value():
    result = find_in_tree(login_tree(), UiQuery(name_contains="password"), UiLimits())
    (m,) = result.matches
    assert m.is_password is True and m.value is None and SECRET not in dump(result.info())


# ---- Fake-Provider -----------------------------------------------------------------------------------------------------------------------
def test_the_fake_provider_is_deterministic_and_describes_a_fixed_tree():
    a, b = FakeUiaProvider(), FakeUiaProvider()
    first = a.describe(NOTEPAD, UiLimits())
    assert first == a.describe(NOTEPAD, UiLimits()) == b.describe(NOTEPAD, UiLimits())
    assert isinstance(first, UiSnapshot) and first.window_handle == NOTEPAD and first.truncated is False
    assert first.root.name == "Untitled - Notepad" and first.root.control_type is ControlType.WINDOW and first.node_count == count(first.root)
    assert {e.control_type.value for e in flat(first.root)} >= {"Window", "MenuBar", "MenuItem", "Edit", "StatusBar", "Text"}
    rids = [e.runtime_id for e in flat(first.root)]
    assert len(rids) == len(set(rids))                                           # stabile, eindeutige Kennungen


def test_the_fake_provider_applies_the_limits():
    snap = FakeUiaProvider().describe(NOTEPAD, UiLimits(max_depth=1, max_nodes=200, max_text=50))
    assert depth_of(snap.root) == 1 and snap.truncated is True
    assert FakeUiaProvider().describe(NOTEPAD, UiLimits(max_nodes=3)).node_count == 3


def test_the_fake_provider_finds_elements():
    result = FakeUiaProvider().find(NOTEPAD, UiQuery(control_type="Edit"), UiLimits())
    assert isinstance(result, UiFindResult) and [m.name for m in result.matches] == ["Text editor"] and result.matches[0].automation_id == "15"


def test_the_login_window_hides_the_password_in_every_view():
    p = FakeUiaProvider()
    blob = dump(p.describe(LOGIN, UiLimits()).info()) + dump(p.find(LOGIN, UiQuery(), UiLimits()).info()) + repr(p.describe(LOGIN, UiLimits()))
    assert SECRET not in blob and "alice" not in repr(p.describe(LOGIN, UiLimits()))        # auch normale Werte nicht in reprs
    assert any(e.is_password for e in flat(p.describe(LOGIN, UiLimits()).root))


@pytest.mark.parametrize("handle", [999, 0, -5])
def test_an_unknown_window_is_a_controlled_error(handle):
    with pytest.raises(ComputerError) as exc:
        FakeUiaProvider().describe(handle, UiLimits())
    assert exc.value.code is ErrorCode.WINDOW_NOT_FOUND
    with pytest.raises(ComputerError) as exc:
        FakeUiaProvider().find(handle, UiQuery(), UiLimits())
    assert exc.value.code is ErrorCode.WINDOW_NOT_FOUND


@pytest.mark.parametrize("handle", ["1001", None, True, 1.5])
def test_an_invalid_window_handle_is_rejected(handle):
    with pytest.raises(ComputerError) as exc:
        FakeUiaProvider().describe(handle, UiLimits())
    assert exc.value.code is ErrorCode.INVALID_INPUT


def test_the_fake_records_calls_and_can_fail_once():
    p = FakeUiaProvider()
    p.describe(NOTEPAD, UiLimits())
    p.find(NOTEPAD, UiQuery(), UiLimits())
    assert [c[0] for c in p.calls] == ["describe", "find"]
    p.fail_next(ComputerError(ErrorCode.BACKEND_ERROR, "simuliert"))
    with pytest.raises(ComputerError):
        p.describe(NOTEPAD, UiLimits())
    assert p.describe(NOTEPAD, UiLimits()).node_count > 0                      # nur einmal


def test_a_custom_tree_can_be_injected_and_is_bounded_like_any_other():
    p = FakeUiaProvider({7: wide(1000)})
    assert p.describe(7, UiLimits(HARD_MAX_DEPTH, HARD_MAX_NODES, HARD_MAX_TEXT)).node_count == HARD_MAX_NODES


# ---- Schnittstelle: nur Lesen --------------------------------------------------------------------------------------------------------------
def test_the_provider_interface_is_read_only_and_abstract():
    public = {n for n in dir(UiTreeProvider) if not n.startswith("_")}
    assert public == {"describe", "find", "name"}
    assert set(UiTreeProvider.__abstractmethods__) == {"describe", "find"}
    with pytest.raises(TypeError):
        UiTreeProvider()                                        # type: ignore[abstract]


def test_the_fake_has_no_way_to_act():
    p = FakeUiaProvider()
    for verb in ("click", "invoke", "set_value", "set_text", "type_text", "type_keys", "press", "focus", "close", "kill", "terminate", "launch", "select", "toggle"):
        assert not hasattr(p, verb), verb


def test_the_backend_bundle_gets_an_optional_ui_slot_without_changing_existing_backends():
    from jarvis.computer.providers.fake import FakeBackend
    assert ComputerBackend("leer").ui is None
    assert FakeBackend().bundle().capabilities() == ["screen", "mouse", "keyboard", "windows", "apps"]
    with_ui = ComputerBackend("mit-ui", ui=FakeUiaProvider())
    assert with_ui.capabilities() == ["ui"]


# ---- Aufbau: keine Bibliothek, keine Tools, keine Aktivierung ----------------------------------------------------------------------------
NEW_FILES = [COMP / "uia.py", COMP / "providers" / "fake_uia.py"]


def test_the_new_modules_use_no_automation_library_no_process_no_network_no_ctypes():
    for path in NEW_FILES:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"(?m)^\s*(import|from)\s+(pywinauto|comtypes|pythoncom|win32\w*|ctypes|subprocess|socket|urllib|http|requests|os|shutil|random|time|datetime)\b", text), path.name
        assert "pywinauto" not in text.replace("pywinauto-Beobachtung", "") or path.name == "uia.py"       # nur in einer Dokumentationszeile erlaubt
    assert not re.search(r"(?mi)^\s*(import|from)\s+pywinauto", (COMP / "uia.py").read_text(encoding="utf-8"))


def test_importing_the_model_loads_no_automation_library():
    for name in ("pywinauto", "comtypes", "pythoncom", "win32api"):
        assert name not in sys.modules, name


def test_no_tool_or_setting_or_dependency_was_added():
    assert "uia" not in (COMP / "tools.py").read_text(encoding="utf-8").lower() and "ui_tree" not in (COMP / "resources.py").read_text(encoding="utf-8")
    from jarvis.config import ComputerSettings
    assert not [f.name for f in dataclasses.fields(ComputerSettings) if "uia" in f.name or f.name.startswith("ui")]
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in pyproject and "pywinauto" not in pyproject
    assert "uia" not in (ROOT / "config" / "jarvis.toml").read_text(encoding="utf-8").lower()


def test_the_model_never_calls_acting_methods():
    import ast
    acting = {"click", "move", "scroll", "press", "hotkey", "type_text", "launch", "focus", "minimize", "maximize", "restore", "close", "capture", "invoke", "kill", "terminate"}
    for path in NEW_FILES:
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                assert n.func.attr not in acting, f"{path.name}: .{n.func.attr}()"
