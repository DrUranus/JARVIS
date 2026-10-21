
"""Grafische Oberfläche für JARVIS (Phase 11): Gespräch per Text oder Sprache, sichtbare Zustände, Status, sichere GUI-Bestätigungen.

Alle Logik (Zustände, Hintergrundarbeit, Voice, Status) liegt toolkitfrei in `gui_model.py`; diese Datei zeichnet nur. Hintergrundthreads fassen
keine Widgets an: sie melden Ereignisse, die der GUI-Thread in `_poll` abholt.
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Sequence

from jarvis.bootstrap import build_core
from jarvis.config import load_settings
from jarvis.errors import JarvisError
from jarvis.interface.gui_model import (KIND_LABELS, ActivityEvent, ActivitySnapshot, CallEvent, ChatEvent, CloseEvent, EmergencyEvent, GuiController, InputEvent, StateEvent, StatusEvent,
                                        SubmitResult, UiState)
from jarvis.permissions.confirmation import (
    ConfirmationChoice,
    ConfirmationProvider,
    ConfirmationRequest,
)

log = logging.getLogger("jarvis.interface.gui")


class GUIConfirmationProvider(ConfirmationProvider):
    """Zeigt Bestätigungen im GUI-Hauptthread an. Fehler bedeuten DENY."""

    def __init__(self, root: tk.Tk, timeout: float = 120.0, *, dispatch: Callable[..., None] | None = None,
                 on_wait: Callable[[bool], None] | None = None) -> None:
        """`dispatch(fn, *args)` must run fn on the GUI thread and be callable from any thread (the GUI passes its event queue; the default is Tk's `after`).
        `on_wait(True/False)` reports that a question is open / answered, so that the state "wartet auf Bestätigung" is real."""
        self.root = root
        self.timeout = timeout
        self._dispatch_fn = dispatch
        self._on_wait = on_wait
        self._lock = threading.Lock()
        self._pending: dict[int, dict[str, Any]] = {}
        self._closing = False

    def _dispatch(self, fn: Callable[..., None], *args: Any) -> None:
        dispatch = getattr(self, "_dispatch_fn", None)
        if dispatch is not None:
            dispatch(fn, *args)
        else:
            self.root.after(0, fn, *args)

    def _waiting(self, waiting: bool) -> None:
        notify = getattr(self, "_on_wait", None)
        if notify is not None:
            try:
                notify(waiting)
            except Exception:
                log.exception("Statusmeldung der Bestätigung fehlgeschlagen.")

    def confirm(self, request: ConfirmationRequest) -> ConfirmationChoice:
        record: dict[str, Any] = {
            "event": threading.Event(),
            "choice": ConfirmationChoice.DENY,
            "dialog": None,
        }

        with self._lock:
            if self._closing:
                return ConfirmationChoice.DENY
            self._pending[id(record)] = record

        try:
            self._dispatch(self._show_dialog, request, record)
        except Exception:
            log.exception("GUI-Bestätigung konnte nicht geöffnet werden.")
            self._resolve(record, ConfirmationChoice.DENY)
            with self._lock:
                self._pending.pop(id(record), None)
            return ConfirmationChoice.DENY

        self._waiting(True)
        try:
            if not record["event"].wait(self.timeout):
                self._resolve(record, ConfirmationChoice.DENY)
                try:
                    self._dispatch(self._close_dialog, record)
                except Exception:
                    pass
        finally:
            self._waiting(False)
            with self._lock:
                self._pending.pop(id(record), None)

        return record["choice"]

    def _resolve(
        self,
        record: dict[str, Any],
        choice: ConfirmationChoice,
    ) -> None:
        with self._lock:
            if record["event"].is_set():
                return
            record["choice"] = choice
            record["event"].set()

    
    def _show_dialog(
        self,
        request: ConfirmationRequest,
        record: dict[str, Any],
    ) -> None:
        with self._lock:
            should_deny = self._closing or record["event"].is_set()

        if should_deny:
            self._resolve(record, ConfirmationChoice.DENY)
            return


        dialog = tk.Toplevel(self.root)
        record["dialog"] = dialog
        dialog.title("JARVIS – Aktion bestätigen")
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.geometry("540x390")
        dialog.minsize(420, 300)

        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        ttk.Label(
            frame,
            text="JARVIS benötigt deine Bestätigung",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))

        details = tk.Text(frame, wrap="word", height=10, width=55)
        details.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        details.insert("1.0", request.to_text())
        details.configure(state="disabled")

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, sticky="e")

        def choose(choice: ConfirmationChoice) -> None:
            self._resolve(record, choice)
            self._close_dialog(record)

        ttk.Button(
            buttons,
            text="Ablehnen",
            command=lambda: choose(ConfirmationChoice.DENY),
        ).pack(side="right", padx=(8, 0))

        if request.session_allowed:
            ttk.Button(
                buttons,
                text="Für Sitzung erlauben",
                command=lambda: choose(ConfirmationChoice.ALLOW_SESSION),
            ).pack(side="right", padx=(8, 0))

        ttk.Button(
            buttons,
            text="Einmal erlauben",
            command=lambda: choose(ConfirmationChoice.ALLOW_ONCE),
        ).pack(side="right")

        dialog.protocol(
            "WM_DELETE_WINDOW",
            lambda: choose(ConfirmationChoice.DENY),
        )
        dialog.bind(
            "<Escape>",
            lambda _event: choose(ConfirmationChoice.DENY),
        )
        dialog.focus_set()

    def _close_dialog(self, record: dict[str, Any]) -> None:
        dialog = record.get("dialog")
        if dialog is not None:
            try:
                if dialog.winfo_exists():
                    dialog.destroy()
            except tk.TclError:
                pass
            record["dialog"] = None

    def deny_pending(self) -> int:
        """Answer every open confirmation with DENY (emergency stop). Unlike close_pending the provider keeps working afterwards (for the reset question)."""
        with self._lock:
            records = list(self._pending.values())
        for record in records:
            self._resolve(record, ConfirmationChoice.DENY)
            try:
                self._dispatch(self._close_dialog, record)
            except Exception:
                pass
        return len(records)

    def close_pending(self) -> None:
        """Beim Schließen der Anwendung alle offenen Bestätigungen ablehnen."""
        with self._lock:
            self._closing = True
            records = list(self._pending.values())

        for record in records:
            self._resolve(record, ConfirmationChoice.DENY)
            self._close_dialog(record)


STATE_STYLE: dict[UiState, str] = {            # Farbe des Zustandspunkts; weitere Zustände/Animationen kommen hier und in _apply_state dazu
    UiState.READY: "#2e7d32", UiState.LISTENING: "#1565c0", UiState.PROCESSING: "#ef6c00", UiState.SPEAKING: "#6a1b9a",
    UiState.AWAITING_CONFIRMATION: "#c62828", UiState.ERROR: "#b71c1c", UiState.EMERGENCY: "#000000",
}
POLL_MS = 50


def _ask_close() -> bool:
    return messagebox.askyesno("JARVIS beenden", "Eine Anfrage oder der Sprachmodus läuft noch.\nTrotzdem schließen? Laufende Aktionen werden angehalten.")


class JarvisGUI:
    """Das Fenster. `controller` und `confirm_close` sind für Tests austauschbar."""

    def __init__(self, root: tk.Tk, core: Any, settings: Any = None, *, controller: GuiController | None = None,
                 confirm_close: Callable[[], bool] | None = None) -> None:
        self.root = root
        self.core = core
        self.controller = controller or GuiController(core, settings)
        self._confirm_close = confirm_close or _ask_close
        self._closing = False
        self._after_id: str | None = None
        self.confirmation_provider = GUIConfirmationProvider(root, dispatch=self.controller.call_in_gui, on_wait=self.controller.confirmation_waiting)
        self.controller.set_confirmation_denier(self.confirmation_provider.deny_pending)
        self.root.title("JARVIS – Personal AI Assistant")
        self.root.geometry("1000x700")
        self.root.minsize(760, 520)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        self.controller.say("JARVIS", "Die GUI ist verbunden. Schreibe eine Nachricht" + (" oder starte den Sprachmodus." if settings is not None else "."))
        self._apply_state(UiState.READY, "")
        self._after_id = self.root.after(POLL_MS, self._poll)

    # -- Aufbau -------------------------------------------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=(16, 12))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="JARVIS", font=("Segoe UI", 20, "bold")).grid(row=0, column=0, sticky="w")
        emergency = ttk.Frame(header)
        emergency.grid(row=0, column=2, sticky="e", padx=(0, 16))
        self.emergency_button = tk.Button(emergency, text="NOTAUS", command=self._on_emergency, bg="#b71c1c", fg="white", activebackground="#7f0000",
                                          activeforeground="white", font=("Segoe UI", 12, "bold"), padx=16, pady=4,
                                          state="normal" if self.controller.emergency_available else "disabled")
        self.emergency_button.grid(row=0, column=0)
        self.reset_button = ttk.Button(emergency, text="Notaus aufheben …", command=self._on_reset_emergency, state="disabled")
        self.reset_button.grid(row=0, column=1, padx=(8, 0))
        status = ttk.Frame(header)
        status.grid(row=0, column=3, sticky="e")
        self.state_dot = tk.Canvas(status, width=16, height=16, highlightthickness=0)
        self.state_dot.grid(row=0, column=0, padx=(0, 6))
        self._dot = self.state_dot.create_oval(2, 2, 14, 14, fill=STATE_STYLE[UiState.READY], outline="")
        self.state_label = ttk.Label(status, text=UiState.READY.label, font=("Segoe UI", 11, "bold"))
        self.state_label.grid(row=0, column=1)

        self.tabs = ttk.Notebook(self.root)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))

        chat = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(chat, text="Gespräch")
        chat.columnconfigure(0, weight=1)
        chat.rowconfigure(0, weight=1)
        self.output = tk.Text(chat, wrap="word", state="disabled", font=("Segoe UI", 11), padx=12, pady=12)
        self.output.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(chat, orient="vertical", command=self.output.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.output.configure(yscrollcommand=scrollbar.set)
        self.output.tag_configure("sender", font=("Segoe UI", 10, "bold"))
        self.output.tag_configure("system", foreground="#555555")
        self.output.tag_configure("error", foreground="#b71c1c")

        input_frame = ttk.Frame(chat)
        input_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        input_frame.columnconfigure(0, weight=1)
        self.input_field = ttk.Entry(input_frame, font=("Segoe UI", 11))
        self.input_field.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.input_field.bind("<Return>", lambda _event: self._send_message())
        self.send_button = ttk.Button(input_frame, text="Senden", command=self._send_message)
        self.send_button.grid(row=0, column=1, padx=(0, 8))
        self.voice_button = ttk.Button(input_frame, text="Sprache starten", command=self._toggle_voice)
        self.voice_button.grid(row=0, column=2)
        self.hint = ttk.Label(chat, text="", foreground="#555555")
        self.hint.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        status_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(status_tab, text="Status")
        status_tab.columnconfigure(0, weight=1)
        status_tab.rowconfigure(2, weight=1)
        ttk.Button(status_tab, text="Aktualisieren", command=self._refresh_status).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.activity_box = ttk.LabelFrame(status_tab, text="Laufende Arbeit", padding=8)
        self.activity_box.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.activity_box.columnconfigure(0, weight=1)
        self.activity_rows: list[ttk.Frame] = []
        self.activity_hint = ttk.Label(self.activity_box, text="Noch nicht abgerufen. „Aktualisieren“ liest laufende Ziele, Agenten-Tasks, Reparaturläufe und Pläne.", wraplength=820,
                                       justify="left")
        self.activity_hint.grid(row=0, column=0, sticky="w")
        self.status_text = tk.Text(status_tab, wrap="word", state="disabled", font=("Consolas", 10), padx=8, pady=8)
        self.status_text.grid(row=2, column=0, sticky="nsew")
        self._set_status_text("Noch nicht abgerufen. „Aktualisieren“ liest Subsysteme, Aufgaben, Ziele und Berechtigungen (nur lesend).")
        self.tabs.bind("<<NotebookTabChanged>>", lambda _e: self._refresh_status() if self.tabs.index("current") == 1 else None)

    # -- Ereignisse (nur der GUI-Thread) ----------------------------------------------------------------------------
    def _poll(self) -> None:
        self._after_id = None
        if self._closing:
            return
        try:
            for event in self.controller.drain():
                try:
                    self._handle(event)
                except Exception:
                    log.exception("GUI-Ereignis konnte nicht verarbeitet werden: %r", type(event).__name__)
        finally:
            if not self._closing:
                self._after_id = self.root.after(POLL_MS, self._poll)

    def _handle(self, event: Any) -> None:
        if isinstance(event, ChatEvent):
            self._append_entry(event.entry.sender, event.entry.text)
        elif isinstance(event, StateEvent):
            self._apply_state(event.state, event.detail)
        elif isinstance(event, InputEvent):
            self._apply_input(event)
        elif isinstance(event, StatusEvent):
            self._set_status_text("\n\n".join(f"== {title} ==\n{body}" for title, body in event.sections))
        elif isinstance(event, ActivityEvent):
            self._render_activity(event.snapshot)
        elif isinstance(event, EmergencyEvent):
            self._apply_emergency(event.engaged)
        elif isinstance(event, CallEvent):
            event.fn(*event.args)
        elif isinstance(event, CloseEvent):
            self._on_close()

    def _apply_state(self, state: UiState, detail: str) -> None:
        self.state_dot.itemconfigure(self._dot, fill=STATE_STYLE[state])
        self.state_label.configure(text=state.label)
        self.hint.configure(text=detail if state is UiState.ERROR else "")

    def _apply_input(self, event: InputEvent) -> None:
        state = "normal" if event.enabled else "disabled"
        self.input_field.configure(state=state)
        self.send_button.configure(state=state)
        self.voice_button.configure(text="Sprache beenden" if event.voice_active else "Sprache starten",
                                    state="disabled" if (not event.enabled and not event.voice_active) else "normal")
        if self.controller.emergency_engaged:
            self.hint.configure(text=event.reason)
        if event.enabled:
            self.input_field.focus_set()
            if not self.hint.cget("text"):
                self.hint.configure(text="")
        elif event.reason and self.state_label.cget("text") == UiState.READY.label:
            self.hint.configure(text=event.reason)

    def _apply_emergency(self, engaged: bool) -> None:
        self.reset_button.configure(state="normal" if engaged else "disabled")
        self.emergency_button.configure(text="NOTAUS AKTIV" if engaged else "NOTAUS", relief="sunken" if engaged else "raised")

    def _append_entry(self, sender: str, message: str) -> None:
        self.output.configure(state="normal")
        self.output.insert("end", f"{sender}\n", ("sender", "system") if sender == "System" else ("sender",))
        self.output.insert("end", f"{message}\n\n", ("system",) if sender == "System" else ())
        self.output.configure(state="disabled")
        self.output.see("end")

    def _render_activity(self, snap: ActivitySnapshot) -> None:
        """Rebuild the list of unfinished work. Runs on the GUI thread only (called from _poll). One row per item with the cancel button that belongs to it."""
        for row in self.activity_rows:
            row.destroy()
        self.activity_rows = []
        lines = []
        if not snap.items:
            lines.append("Keine laufende Arbeit.")
        if snap.inactive:
            lines.append("Ausgeschaltet (Standard): " + ", ".join(snap.inactive) + ".")
        lines += list(snap.problems)
        self.activity_hint.configure(text="\n".join(lines))
        if snap.items:
            self.activity_hint.grid_configure(pady=(0, 6))
        for i, item in enumerate(snap.items, start=1):
            row = ttk.Frame(self.activity_box)
            row.grid(row=i, column=0, sticky="ew", pady=2)
            row.columnconfigure(1, weight=1)
            ttk.Label(row, text=f"{KIND_LABELS.get(item.kind, item.kind)} · {item.status}", font=("Segoe UI", 9, "bold"), width=26).grid(row=0, column=0, sticky="w")
            ttk.Label(row, text=f"{item.ident}  {item.text}" + (f"   ({item.note})" if item.note else ""), wraplength=520, justify="left").grid(row=0, column=1, sticky="w")
            ttk.Button(row, text="Abbrechen", command=lambda k=item.kind, n=item.ident: self.controller.request_cancel(k, n)).grid(row=0, column=2, padx=(8, 0))
            self.activity_rows.append(row)

    def _set_status_text(self, text: str) -> None:
        self.status_text.configure(state="normal")
        self.status_text.delete("1.0", "end")
        self.status_text.insert("1.0", text)
        self.status_text.configure(state="disabled")

    # -- Aktionen --------------------------------------------------------------------------------------------------------
    def _send_message(self) -> None:
        text = self.input_field.get()
        result = self.controller.submit(text)
        if result in (SubmitResult.STARTED, SubmitResult.HANDLED):
            self.input_field.delete(0, "end")

    def _toggle_voice(self) -> None:
        if self.controller.voice_active:
            self.controller.stop_voice()
            return
        reason = self.controller.start_voice()
        if reason:
            self.controller.say("System", reason)

    def _on_emergency(self) -> None:
        self.controller.emergency_stop()                 # one click, no question: the latch is set at once, the components are stopped in the background

    def _on_reset_emergency(self) -> None:
        self.controller.reset_emergency()                # the permission engine asks for explicit confirmation (dialog); nothing else can lift the stop

    def _refresh_status(self) -> None:
        self.controller.request_status()
        self.controller.request_activity()

    def _on_close(self) -> None:
        if self._closing:
            return
        if self.controller.busy and not self._confirm_close():
            return
        self._closing = True
        notes = self.controller.close()
        if notes:
            log.info("Beim Schließen: %s", "; ".join(notes))
        self.confirmation_provider.close_pending()
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
        self.root.destroy()


def main(argv: Sequence[str] | None = None) -> int:
    from jarvis.interface.cli import _default_config

    parser = argparse.ArgumentParser(prog="jarvis-gui", description="JARVIS graphical interface")
    parser.add_argument("-c", "--config", help="path to a TOML config file")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config or _default_config())
        core = build_core(settings)
    except JarvisError as exc:
        print(f"Startfehler: {exc}", file=sys.stderr)
        return 2

    root = tk.Tk()
    gui = JarvisGUI(root, core, settings)

    # Eine explizite DENY-Konfiguration darf nicht überschrieben werden.
    if settings.security.confirmation != "deny":
        core.tools.permissions.set_confirmation_provider(gui.confirmation_provider, source="gui")

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
