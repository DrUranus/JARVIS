
"""Grafische Oberfläche für JARVIS mit sicheren GUI-Bestätigungen."""
from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any

from jarvis.bootstrap import build_core
from jarvis.config import load_settings
from jarvis.permissions.confirmation import (
    ConfirmationChoice,
    ConfirmationProvider,
    ConfirmationRequest,
)

log = logging.getLogger("jarvis.interface.gui")


class GUIConfirmationProvider(ConfirmationProvider):
    """Zeigt Bestätigungen im GUI-Hauptthread an. Fehler bedeuten DENY."""

    def __init__(self, root: tk.Tk, timeout: float = 120.0) -> None:
        self.root = root
        self.timeout = timeout
        self._lock = threading.Lock()
        self._pending: dict[int, dict[str, Any]] = {}
        self._closing = False

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
            self.root.after(0, self._show_dialog, request, record)
        except Exception:
            log.exception("GUI-Bestätigung konnte nicht geöffnet werden.")
            self._resolve(record, ConfirmationChoice.DENY)
            with self._lock:
                self._pending.pop(id(record), None)
            return ConfirmationChoice.DENY

        if not record["event"].wait(self.timeout):
            self._resolve(record, ConfirmationChoice.DENY)
            try:
                self.root.after(0, self._close_dialog, record)
            except Exception:
                pass

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

    def close_pending(self) -> None:
        """Beim Schließen der Anwendung alle offenen Bestätigungen ablehnen."""
        with self._lock:
            self._closing = True
            records = list(self._pending.values())

        for record in records:
            self._resolve(record, ConfirmationChoice.DENY)
            self._close_dialog(record)


class JarvisGUI:
    def __init__(self, root: tk.Tk, core) -> None:
        self.core = core
        self._busy = False
        self._worker: threading.Thread | None = None
        self.root = root
        self.confirmation_provider = GUIConfirmationProvider(root)
        self.root.title("JARVIS – Personal AI Assistant")
        self.root.geometry("1000x700")
        self.root.minsize(760, 520)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=16)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text="JARVIS",
            font=("Segoe UI", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            header,
            text="Bereit – GUI verbunden",
        ).grid(row=0, column=1, sticky="e")

        main = ttk.Frame(self.root, padding=16)
        main.grid(row=1, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)

        self.output = tk.Text(
            main,
            wrap="word",
            state="disabled",
            font=("Segoe UI", 11),
            padx=12,
            pady=12,
        )
        self.output.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(
            main,
            orient="vertical",
            command=self.output.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.output.configure(yscrollcommand=scrollbar.set)

        input_frame = ttk.Frame(main)
        input_frame.grid(
            row=1, column=0, columnspan=2,
            sticky="ew", pady=(12, 0),
        )
        input_frame.columnconfigure(0, weight=1)

        self.input_field = ttk.Entry(input_frame, font=("Segoe UI", 11))
        self.input_field.grid(
            row=0, column=0, sticky="ew", padx=(0, 8),
        )
        self.input_field.bind(
            "<Return>",
            lambda _event: self._send_message(),
        )

        self.send_button = ttk.Button(
            input_frame,
            text="Senden",
            command=self._send_message,
        )
        self.send_button.grid(row=0, column=1)

        self._append_message(
            "JARVIS",
            "Die GUI ist verbunden. Schreibe eine Nachricht.",
        )

    def _send_message(self) -> None:
        if self._busy:
            return

        message = self.input_field.get().strip()
        if not message:
            return

        self.input_field.delete(0, "end")
        self._append_message("Du", message)

        self._busy = True
        self.send_button.configure(state="disabled")
        self._append_message("JARVIS", "Einen Moment bitte …")

        self._worker = threading.Thread(
            target=self._process_message,
            args=(message,),
            daemon=True,
        )
        self._worker.start()

    def _process_message(self, message: str) -> None:
        try:
            result = self.core.handle(message)
            response = getattr(result, "text", str(result))
        except Exception:
            log.exception("Fehler bei der Verarbeitung einer GUI-Nachricht.")
            response = (
                "Bei der Verarbeitung ist ein Fehler aufgetreten. "
                "Weitere Details stehen im Anwendungsprotokoll."
            )

        try:
            self.root.after(0, self._finish_message, response)
        except tk.TclError:
            log.debug("GUI wurde vor Abschluss der Antwort geschlossen.")

    def _finish_message(self, response: str) -> None:
        self.output.configure(state="normal")
        content = self.output.get("1.0", "end-1c")
        placeholder = "JARVIS\nEinen Moment bitte …\n\n"

        if placeholder in content:
            content = content.rsplit(placeholder, 1)[0]
            self.output.delete("1.0", "end")
            self.output.insert("1.0", content)

        self.output.configure(state="disabled")
        self._append_message("JARVIS", response)
        self._busy = False
        self._worker = None
        self.send_button.configure(state="normal")
        self.input_field.focus_set()

    def _append_message(self, sender: str, message: str) -> None:
        self.output.configure(state="normal")
        self.output.insert("end", f"{sender}\n{message}\n\n")
        self.output.configure(state="disabled")
        self.output.see("end")

    def _on_close(self) -> None:
        self.confirmation_provider.close_pending()
        self.root.destroy()


def main() -> int:
    settings = load_settings()
    core = build_core(settings)

    root = tk.Tk()
    gui = JarvisGUI(root, core)

    # Eine explizite DENY-Konfiguration darf nicht überschrieben werden.
    if settings.security.confirmation != "deny":
        core.tools.permissions.set_confirmation_provider(
            gui.confirmation_provider,
            source="gui",
        )

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())