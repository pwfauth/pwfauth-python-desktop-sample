"""PWF Auth desktop client built with Tkinter on the official ``pwfauth`` package.

The UI deliberately keeps the API response open-ended: every leaf returned by the
server is displayed in the information table and the complete JSON remains available.
"""

from __future__ import annotations

import json
import os
import queue
import re
import threading
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk

from pwfauth import (PwfClient, PwfCryptoError, PwfError, PwfErrorCodes, PwfHttpError,
                     PwfRefusedError, PwfResponse, PwfSecurityError)


# Demo configuration: replace this placeholder with the 64-character secret from
# your PWF Auth dashboard. For production applications, use an environment variable
# instead of embedding the secret in source code.
APP_SECRET = "YOUR_64_CHARACTER_APP_SECRET"

DEFAULT_BASE_URL = "https://pwfauth.com"

COLORS = {
    "page": "#0b1220",
    "card": "#172133",
    "entry": "#0f172a",
    "blue": "#3b82f6",
    "blue_light": "#60a5fa",
    "white": "#ffffff",
    "text": "#0f172a",
    "muted": "#64748b",
    "muted_dark": "#94a3b8",
    "border": "#cbd5e1",
    "surface": "#f1f5f9",
    "success": "#16a34a",
    "warning": "#d97706",
    "error": "#f87171",
    "table_header": "#1e293b",
    "selection": "#dbeafe",
}

FIELD_NAMES = {
    "success": "Request successful",
    "message": "Server message",
    "error_code": "Error code",
    "session_id": "Session ID",
    "heartbeat_interval": "Heartbeat interval",
    "user.license_key": "License key",
    "user.key_type": "Key type",
    "user.duration": "Key duration",
    "user.hwid": "Device HWID",
    "user.activated_at": "Activation date",
    "user.expires_at": "Expiration date",
    "user.days_remaining": "Days remaining",
    "user.status": "Key status",
    "app.name": "Application name",
    "app.version": "Application version",
    "app.message": "Application message",
    "seller.type": "Sold by (type)",
    "seller.name": "Sold by",
    "seller.contact": "Seller contact",
    "texts": "Remote texts",
    "features": "Key features",
    "slides": "Announcement slides",
    "vars": "User variables",
}


def load_app_secret() -> str | None:
    """Return the app secret configured before distribution."""
    value = APP_SECRET.strip()
    if not value or value == "YOUR_64_CHARACTER_APP_SECRET":
        return None
    return value


def load_base_url() -> str:
    """Return the fixed production endpoint."""
    return DEFAULT_BASE_URL


def describe(response: PwfResponse, fallback: str) -> str:
    """The server's message (safe to show the user) plus its error code."""
    message = response.message or fallback
    return f"{message} ({response.error_code})" if response.error_code else message


def touch_user_variables(client: PwfClient) -> dict:
    """User variables (pwfauth 1.5.0): small values kept on the server for this key, such as
    settings, progress or flags. They follow the key to another PC, and the developer sees and
    edits them in the panel (Licences -> the key -> Variables). This sample counts how often
    the key opened it. Runs on the worker thread; never raises, because variables are an extra.
    """
    try:
        try:
            opens = int(client.get_variable("sample_opens") or 0) + 1
        except ValueError:  # text typed into it in the panel
            opens = 1
        client.set_variable("sample_opens", str(opens))
        return {"opens": opens, "vars": client.get_variables()}
    except PwfRefusedError as exc:
        return {"error": f"Not available: {exc} ({exc.error_code})"}
    except PwfError:
        return {}


def parse_server_date(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def normalize_array_path(path: str) -> str:
    return re.sub(r"\[\d+\]", "", path)


class PwfAuthApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PWF Auth - Sign In")
        self.geometry("1084x721")
        self.minsize(900, 650)
        self.configure(bg=COLORS["page"])
        self.protocol("WM_DELETE_WINDOW", self._request_close)

        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._client: PwfClient | None = None
        self._move_key: str | None = None  # the key "Move this license" would move
        self._logging_in = False
        self._closing = False
        self._copy_reset_after: str | None = None

        self._configure_styles()
        self._build_login_page()
        self._build_dashboard()
        self._show_login()
        self.bind("<Return>", self._on_enter)
        self.after(100, self._poll_events)

    # ------------------------------------------------------------------ UI

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Pwf.TNotebook",
            background=COLORS["surface"],
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "Pwf.TNotebook.Tab",
            background="#e2e8f0",
            foreground=COLORS["text"],
            font=("Segoe UI", 10),
            padding=(15, 8),
        )
        style.map(
            "Pwf.TNotebook.Tab",
            background=[("selected", COLORS["white"])],
            foreground=[("selected", COLORS["text"])],
        )
        style.configure(
            "Pwf.Treeview",
            background=COLORS["white"],
            fieldbackground=COLORS["white"],
            foreground=COLORS["text"],
            rowheight=32,
            font=("Segoe UI", 9),
            borderwidth=0,
        )
        style.configure(
            "Pwf.Treeview.Heading",
            background=COLORS["table_header"],
            foreground=COLORS["white"],
            font=("Segoe UI", 10, "bold"),
            padding=(8, 8),
            relief="flat",
        )
        style.map(
            "Pwf.Treeview",
            background=[("selected", COLORS["selection"])],
            foreground=[("selected", COLORS["text"])],
        )
        style.map(
            "Pwf.Treeview.Heading",
            background=[("active", COLORS["table_header"])],
        )

    def _build_login_page(self) -> None:
        self.login_page = tk.Frame(self, bg=COLORS["page"])
        card = tk.Frame(
            self.login_page,
            bg=COLORS["card"],
            width=500,
            height=515,
            highlightthickness=0,
        )
        card.place(relx=0.5, rely=0.5, anchor="center")
        card.pack_propagate(False)

        tk.Frame(card, bg=COLORS["blue"], height=5).pack(fill="x")
        tk.Label(
            card,
            text="◆  PWF AUTH",
            bg=COLORS["card"],
            fg=COLORS["blue_light"],
            font=("Segoe UI", 16, "bold"),
        ).place(x=42, y=45, width=416, height=44)
        tk.Label(
            card,
            text="Welcome Back",
            bg=COLORS["card"],
            fg=COLORS["white"],
            font=("Segoe UI", 18, "bold"),
        ).place(x=42, y=103, width=416, height=42)
        tk.Label(
            card,
            text="Enter your key to connect to the license server\nand view your complete subscription details",
            bg=COLORS["card"],
            fg=COLORS["muted_dark"],
            font=("Segoe UI", 9),
            justify="center",
        ).place(x=42, y=151, width=416, height=42)
        tk.Label(
            card,
            text="License key",
            bg=COLORS["card"],
            fg="#cbd5e1",
            font=("Segoe UI", 9),
            anchor="w",
        ).place(x=42, y=207, width=416, height=23)

        self.license_key_var = tk.StringVar()
        self.license_entry = tk.Entry(
            card,
            textvariable=self.license_key_var,
            bg=COLORS["entry"],
            fg=COLORS["white"],
            insertbackground=COLORS["white"],
            selectbackground=COLORS["blue"],
            relief="flat",
            highlightthickness=1,
            highlightbackground="#64748b",
            highlightcolor=COLORS["blue_light"],
            justify="center",
            font=("Consolas", 13),
        )
        self.license_entry.place(x=42, y=239, width=416, height=30)
        # "Move this license" applies to the key that failed; editing it withdraws the offer.
        self.license_key_var.trace_add("write", lambda *_: self._set_move_visible(False))

        self.login_button = tk.Button(
            card,
            text="Sign In",
            command=self._begin_login,
            bg=COLORS["blue"],
            activebackground="#2563eb",
            fg=COLORS["white"],
            activeforeground=COLORS["white"],
            disabledforeground="#dbeafe",
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI", 11, "bold"),
        )
        self.login_button.place(x=42, y=289, width=416, height=46)

        self.login_progress = ttk.Progressbar(card, mode="indeterminate")
        self.login_status = tk.Label(
            card,
            text="",
            bg=COLORS["card"],
            fg=COLORS["error"],
            font=("Segoe UI", 9),
            justify="center",
            wraplength=410,
        )
        self.login_status.place(x=42, y=358, width=416, height=44)

        # Shown only when the key is bound to another computer (HWID_MISMATCH or
        # DEVICE_LIMIT): a self-service move, then sign-in here.
        # The 1-pixel blue frame around it is the button's outline.
        self.move_frame = tk.Frame(card, bg=COLORS["blue"])
        self.move_button = tk.Button(
            self.move_frame,
            text="Move this license to this PC",
            command=self._begin_move,
            bg=COLORS["card"],
            activebackground="#1e293b",
            fg=COLORS["blue_light"],
            activeforeground=COLORS["white"],
            disabledforeground="#64748b",
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        )
        self.move_button.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(
            card,
            text="Encrypted connection  •  Key bound to this device",
            bg=COLORS["card"],
            fg="#8b97ad",
            font=("Segoe UI", 9),
        ).place(x=42, y=466, width=416, height=22)

    def _build_dashboard(self) -> None:
        self.dashboard = tk.Frame(self, bg=COLORS["surface"], padx=22)

        header = tk.Frame(self.dashboard, bg=COLORS["surface"], height=96)
        header.pack(fill="x")
        header.pack_propagate(False)
        left_header = tk.Frame(header, bg=COLORS["surface"])
        left_header.pack(side="left", fill="both", expand=True)
        self.dashboard_title = tk.Label(
            left_header,
            text="License Information",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=("Segoe UI", 20, "bold"),
            anchor="w",
        )
        self.dashboard_title.pack(fill="x", pady=(13, 0))
        self.dashboard_subtitle = tk.Label(
            left_header,
            text="",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.dashboard_subtitle.pack(fill="x")

        right_header = tk.Frame(header, bg=COLORS["surface"])
        right_header.pack(side="right", padx=(10, 0), pady=28)
        self.session_status = tk.Label(
            right_header,
            text="● Session active and protected",
            bg=COLORS["surface"],
            fg=COLORS["success"],
            font=("Segoe UI", 9, "bold"),
        )
        self.session_status.pack(side="left", padx=(0, 15))
        self.logout_button = tk.Button(
            right_header,
            text="Sign Out",
            command=self._begin_logout,
            bg=COLORS["white"],
            activebackground="#e2e8f0",
            fg="#334155",
            relief="solid",
            bd=1,
            cursor="hand2",
            font=("Segoe UI", 9),
            width=14,
        )
        self.logout_button.pack(side="right", ipady=8)

        summary = tk.Frame(self.dashboard, bg=COLORS["surface"], height=122)
        summary.pack(fill="x", pady=(8, 8))
        summary.pack_propagate(False)
        for column in range(4):
            summary.grid_columnconfigure(column, weight=1, uniform="summary")
        summary.grid_rowconfigure(0, weight=1)

        self.status_value = self._make_summary_card(summary, 0, "KEY STATUS", COLORS["success"])
        self.type_value = self._make_summary_card(summary, 1, "SUBSCRIPTION TYPE", COLORS["text"])
        self.expiry_value = self._make_summary_card(summary, 2, "EXPIRATION DATE", COLORS["text"], 13)
        self.remaining_value = self._make_summary_card(summary, 3, "TIME REMAINING", "#2563eb")

        notebook = ttk.Notebook(self.dashboard, style="Pwf.TNotebook")
        notebook.pack(fill="both", expand=True)
        details_tab = tk.Frame(notebook, bg=COLORS["white"], padx=8, pady=8)
        json_tab = tk.Frame(notebook, bg=COLORS["white"], padx=8, pady=8)
        notebook.add(details_tab, text="All Information")
        notebook.add(json_tab, text="Complete JSON")

        columns = ("field", "path", "value")
        self.details_tree = ttk.Treeview(
            details_tab,
            columns=columns,
            show="headings",
            style="Pwf.Treeview",
            selectmode="browse",
        )
        self.details_tree.heading("field", text="Field", anchor="w")
        self.details_tree.heading("path", text="API Path", anchor="w")
        self.details_tree.heading("value", text="Value", anchor="w")
        self.details_tree.column("field", width=220, minwidth=140, anchor="w", stretch=False)
        self.details_tree.column("path", width=230, minwidth=150, anchor="w", stretch=False)
        self.details_tree.column("value", width=520, minwidth=220, anchor="w", stretch=True)
        tree_y = ttk.Scrollbar(details_tab, orient="vertical", command=self.details_tree.yview)
        tree_x = ttk.Scrollbar(details_tab, orient="horizontal", command=self.details_tree.xview)
        self.details_tree.configure(yscrollcommand=tree_y.set, xscrollcommand=tree_x.set)
        self.details_tree.grid(row=0, column=0, sticky="nsew")
        tree_y.grid(row=0, column=1, sticky="ns")
        tree_x.grid(row=1, column=0, sticky="ew")
        details_tab.grid_rowconfigure(0, weight=1)
        details_tab.grid_columnconfigure(0, weight=1)
        self.details_tree.tag_configure("even", background=COLORS["white"])
        self.details_tree.tag_configure("odd", background="#f8fafc")

        json_toolbar = tk.Frame(json_tab, bg=COLORS["white"], height=48)
        json_toolbar.pack(fill="x")
        json_toolbar.pack_propagate(False)
        tk.Label(
            json_toolbar,
            text="The complete original response returned by the server",
            bg=COLORS["white"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(side="left", fill="both", expand=True)
        self.copy_button = tk.Button(
            json_toolbar,
            text="Copy JSON",
            command=self._copy_json,
            bg="#334155",
            activebackground="#1e293b",
            fg=COLORS["white"],
            activeforeground=COLORS["white"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI", 9),
            width=14,
        )
        self.copy_button.pack(side="right", fill="y")

        json_body = tk.Frame(json_tab, bg=COLORS["entry"])
        json_body.pack(fill="both", expand=True)
        json_y = ttk.Scrollbar(json_body, orient="vertical")
        json_x = ttk.Scrollbar(json_body, orient="horizontal")
        self.raw_json = tk.Text(
            json_body,
            bg=COLORS["entry"],
            fg="#e2e8f0",
            insertbackground=COLORS["white"],
            selectbackground=COLORS["blue"],
            relief="flat",
            bd=0,
            wrap="none",
            font=("Consolas", 10),
            padx=12,
            pady=10,
            state="disabled",
            yscrollcommand=json_y.set,
            xscrollcommand=json_x.set,
        )
        json_y.configure(command=self.raw_json.yview)
        json_x.configure(command=self.raw_json.xview)
        self.raw_json.grid(row=0, column=0, sticky="nsew")
        json_y.grid(row=0, column=1, sticky="ns")
        json_x.grid(row=1, column=0, sticky="ew")
        json_body.grid_rowconfigure(0, weight=1)
        json_body.grid_columnconfigure(0, weight=1)

        self.session_info = tk.Label(
            self.dashboard,
            text="",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI", 8),
            anchor="w",
        )
        self.session_info.pack(fill="x", ipady=10)

    def _make_summary_card(
        self,
        parent: tk.Frame,
        column: int,
        caption: str,
        value_color: str,
        value_size: int = 16,
    ) -> tk.Label:
        card = tk.Frame(parent, bg=COLORS["white"], padx=18, pady=12)
        card.grid(row=0, column=column, sticky="nsew", padx=5)
        tk.Label(
            card,
            text=caption,
            bg=COLORS["white"],
            fg=COLORS["muted"],
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(fill="x")
        value = tk.Label(
            card,
            text="—",
            bg=COLORS["white"],
            fg=value_color,
            font=("Segoe UI", value_size, "bold"),
            anchor="w",
        )
        value.pack(fill="both", expand=True)
        return value

    # ----------------------------------------------------------- login/logout

    def _on_enter(self, _event: tk.Event) -> None:
        if self.login_page.winfo_ismapped() and not self._logging_in:
            self._begin_login()

    def _begin_login(self) -> None:
        license_key = self.license_key_var.get().strip().upper()
        if not license_key:
            self._set_login_message("Enter your license key first.", error=True)
            self.license_entry.focus_set()
            return
        self._start_sign_in(license_key, move_first=False)

    def _begin_move(self) -> None:
        if self._move_key:
            self._start_sign_in(self._move_key, move_first=True)

    # Shared by Sign In and "Move this license to this PC". move_first = the user agreed
    # to unbind the key from the computer it is bound to, then sign in here.
    def _start_sign_in(self, license_key: str, *, move_first: bool) -> None:
        if self._logging_in:
            return
        app_secret = load_app_secret()
        if not app_secret:
            self._set_login_message(
                "The application secret is not configured. Replace APP_SECRET at the top "
                "of app.py with your 64-character application secret.",
                error=True,
            )
            return

        self._set_move_visible(False)
        self._set_login_busy(True)
        self._set_login_message(
            "Moving the license to this computer..." if move_first
            else "Verifying the key and connecting to the server...",
            error=False,
        )
        threading.Thread(
            target=self._login_worker,
            args=(app_secret, load_base_url(), license_key, move_first),
            daemon=True,
            name="pwfauth-login",
        ).start()

    def _login_worker(self, app_secret: str, base_url: str, license_key: str,
                      move_first: bool) -> None:
        client: PwfClient | None = None
        try:
            client = PwfClient(app_secret, base_url=base_url)
            session_client = client
            client.on_session_ended = (
                lambda code, message: self._session_ended_callback(session_client, code, message)
            )

            if move_first:
                # Self-service move: unbinds the key from every computer it is bound to,
                # so the login below binds it here. The developer's cooldown (12 hours by
                # default) applies between two moves.
                moved = client.reset_hardware_id(license_key, "Moved with the Python desktop sample")
                if not moved.success:
                    self._events.put(("login_failed", describe(moved, "The license could not be moved.")))
                    return

            response = client.login(license_key)
            if not response.success:
                if response.error_code in (PwfErrorCodes.HWID_MISMATCH, PwfErrorCodes.DEVICE_LIMIT):
                    self._events.put(("bound_elsewhere", (license_key, response.error_code)))
                else:
                    self._events.put(("login_failed", describe(response, "Sign-in failed.")))
                return

            # The heartbeat keeps the session alive AND enforces the kill switch. It uses
            # the interval the server sent at sign-in.
            client.start_heartbeat()
            variables = touch_user_variables(client)
            self._events.put(("login_succeeded", (client, response, variables)))
            client = None
        except PwfSecurityError:
            self._events.put((
                "login_failed",
                "The reply claimed success without encryption, so it did not come from the "
                "license server. A proxy, a hosts-file entry or a fake server is in the way.",
            ))
        except PwfCryptoError as exc:
            self._events.put((
                "login_failed",
                f"The encrypted response could not be verified. Check the application secret.\n{exc}",
            ))
        except PwfHttpError as exc:
            if exc.status == 0:
                # No connection at all: offline, DNS, firewall, proxy or TLS.
                message = "Cannot reach the license server. Check your internet connection and try again."
            elif exc.status == 401:
                message = ("The license server refused the application secret (HTTP 401). "
                           "Check APP_SECRET in app.py.")
            else:
                message = f"The license server did not return a valid response (HTTP {exc.status}).\n{exc}"
            self._events.put(("login_failed", message))
        except PwfError as exc:
            self._events.put(("login_failed", str(exc)))
        except Exception as exc:  # UI boundary: never let a worker silently die.
            self._events.put(("login_failed", f"An unexpected error occurred: {exc}"))
        finally:
            if client is not None:
                client.stop_heartbeat()

    def _begin_logout(self) -> None:
        client = self._client
        if client is None:
            self._show_login()
            return
        self.logout_button.configure(state="disabled")
        self.session_status.configure(text="Closing session...", fg=COLORS["warning"])
        threading.Thread(
            target=self._logout_worker,
            args=(client, False),
            daemon=True,
            name="pwfauth-logout",
        ).start()

    def _logout_worker(self, client: PwfClient, close_after: bool) -> None:
        warning = ""
        try:
            if client.is_signed_in:
                # None = the server could not be reached; it ends the session on its own
                # timeout. The key stays bound to this computer either way.
                if client.logout() is None:
                    warning = "Signed out locally, but the server could not be notified."
            else:
                client.stop_heartbeat()
        except Exception as exc:
            client.stop_heartbeat()
            warning = f"Signed out locally, but the server could not be notified: {exc}"
        self._events.put(("logout_finished", (client, close_after, warning)))

    def _session_ended_callback(self, client: PwfClient, error_code: str | None,
                                message: str | None) -> None:
        # Called by the SDK heartbeat thread when the key was banned, paused, expired,
        # reset or revoked, maintenance started, or the server stopped answering (or kept
        # refusing this computer's clock). Tk must only be touched on its main thread.
        self._events.put((
            "session_ended",
            (client, error_code or "UNKNOWN", message or "The session is no longer valid."),
        ))

    # ---------------------------------------------------------- event handling

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self._events.get_nowait()
                if event == "login_succeeded":
                    client, response, variables = payload  # type: ignore[misc]
                    self._client = client
                    self._populate_dashboard(response, variables)
                    self._set_login_busy(False)
                    self._show_dashboard()
                elif event == "login_failed":
                    self._set_login_busy(False)
                    self._set_login_message(str(payload), error=True)
                elif event == "bound_elsewhere":
                    license_key, error_code = payload  # type: ignore[misc]
                    self._set_login_busy(False)
                    self._set_login_message(
                        f"This key is bound to another computer ({error_code}).\n"
                        "You can move it here — it then stops working on the other one.",
                        error=True,
                    )
                    self._move_key = license_key
                    self._set_move_visible(True)
                elif event == "session_ended":
                    client, error_code, message = payload  # type: ignore[misc]
                    if client is not self._client:
                        continue  # a session this window already left
                    client.stop_heartbeat()
                    self._client = None
                    self._show_login()
                    self._set_login_message(
                        f"Session ended: {message} ({error_code})",
                        error=True,
                    )
                elif event == "logout_finished":
                    client, close_after, warning = payload  # type: ignore[misc]
                    if self._client is client:
                        self._client = None
                    if close_after:
                        self.destroy()
                        return
                    self.logout_button.configure(state="normal")
                    self._show_login()
                    self._set_login_message(warning, error=bool(warning))
        except queue.Empty:
            pass

        if self.winfo_exists():
            self.after(100, self._poll_events)

    # ---------------------------------------------------------- data display

    def _populate_dashboard(self, response: object, variables: dict | None = None) -> None:
        data = response.data  # PwfResponse; kept untyped to support future SDK growth.
        license_info = response.license
        app = data.get("app") if isinstance(data.get("app"), dict) else {}

        app_name = app.get("name") if isinstance(app.get("name"), str) else ""
        app_version = app.get("version") if isinstance(app.get("version"), str) else ""
        app_message = app.get("message") if isinstance(app.get("message"), str) else ""
        seller = data.get("seller") if isinstance(data.get("seller"), dict) else {}
        seller_name = seller.get("name") if isinstance(seller.get("name"), str) else ""
        license_key = license_info.license_key if license_info else ""

        self.dashboard_title.configure(
            text=f"{app_name} — License Information" if app_name else "License Information"
        )
        variables = variables or {}
        opens = variables.get("opens")
        subtitle_parts = [part for part in (
            license_key,
            f"Version {app_version}" if app_version else "",
            f"Sold by {seller_name}" if seller_name else "",
            app_message,
            f"Opened {opens} time{'' if opens == 1 else 's'} with this key" if opens else "",
        ) if part]
        self.dashboard_subtitle.configure(text="  •  ".join(subtitle_parts))

        status = license_info.status if license_info else None
        self.status_value.configure(text=self._display_status(status))
        self.type_value.configure(text=self._display_key_type(license_info))
        self.expiry_value.configure(text=self._display_expiry(license_info))
        self.remaining_value.configure(text=self._display_remaining(license_info))
        self.session_status.configure(
            text="● Session active and protected",
            fg=COLORS["success"],
        )

        client = self._client
        self.session_info.configure(text=(
            f"Device ID: {client.hardware_id}   •   Heartbeat every {client.heartbeat_interval:g} seconds"
            f"   •   Session ID: {client.session_id}"
        ) if client else "")

        for item in self.details_tree.get_children():
            self.details_tree.delete(item)
        rows: list[tuple[str, object]] = []
        self._flatten_json(data, "", rows)
        # the key's user variables, after the login reply's fields
        rows.extend((f"vars.{name}", value) for name, value in sorted((variables.get("vars") or {}).items()))
        if variables.get("error"):
            rows.append(("vars", variables["error"]))
        for index, (path, value) in enumerate(rows):
            normalized = normalize_array_path(path)
            display_name = FIELD_NAMES.get(path) or FIELD_NAMES.get(normalized)
            if not display_name and normalized.startswith("vars."):
                display_name = f"Variable: {normalized[5:]}"
            if not display_name:
                display_name = normalized.rsplit(".", 1)[-1] if normalized else "Value"
            self.details_tree.insert(
                "",
                "end",
                values=(display_name, path, self._format_json_value(path, value)),
                tags=("even" if index % 2 == 0 else "odd",),
            )

        formatted = json.dumps(data, indent=2, ensure_ascii=False)
        self.raw_json.configure(state="normal")
        self.raw_json.delete("1.0", "end")
        self.raw_json.insert("1.0", formatted)
        self.raw_json.configure(state="disabled")

    def _flatten_json(
        self,
        value: object,
        path: str,
        rows: list[tuple[str, object]],
    ) -> None:
        if isinstance(value, dict):
            if not value and path:
                rows.append((path, {}))
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                self._flatten_json(child, child_path, rows)
            return
        if isinstance(value, list):
            if not value:
                rows.append((path, []))
            for index, child in enumerate(value):
                self._flatten_json(child, f"{path}[{index}]", rows)
            return
        rows.append((path, value))

    def _format_json_value(self, path: str, value: object) -> str:
        if value is None:
            if path.endswith("expires_at") or path.endswith("days_remaining"):
                return "Lifetime (null)"
            return "null"
        if isinstance(value, bool):
            return "true (Yes)" if value else "false (No)"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, str) and (path.endswith("_at") or path.endswith("_date")):
            parsed = parse_server_date(value)
            if parsed is not None:
                local = parsed.astimezone()
                # Keep the server text reachable while presenting the local instant clearly.
                return f"{local:%Y/%m/%d %H:%M:%S} Local  |  {value}"
        return str(value)

    @staticmethod
    def _display_status(status: str | None) -> str:
        return {
            "active": "Active",
            "paused": "Paused",
            "expired": "Expired",
            "banned": "Banned",
        }.get((status or "").lower(), status or "Active")

    @staticmethod
    def _display_key_type(license_info: object) -> str:
        if license_info is None:
            return "Not specified"
        if license_info.is_lifetime:
            return "Lifetime"
        key_type = license_info.key_type or "Not specified"
        return f"{license_info.duration} {key_type}" if license_info.duration is not None else key_type

    @staticmethod
    def _display_expiry(license_info: object) -> str:
        if license_info is None or license_info.is_lifetime:
            return "Never expires"
        return license_info.expires_at.astimezone().strftime("%Y/%m/%d  %H:%M")

    @staticmethod
    def _display_remaining(license_info: object) -> str:
        if license_info is None or license_info.is_lifetime:
            return "Lifetime"
        days = license_info.days_remaining
        return f"{days} days" if days is not None else "Not specified"

    # ------------------------------------------------------------ view state

    def _show_login(self) -> None:
        self.dashboard.pack_forget()
        self.login_page.pack(fill="both", expand=True)
        self.title("PWF Auth - Sign In")
        self.license_entry.focus_set()

    def _show_dashboard(self) -> None:
        self.login_page.pack_forget()
        self.dashboard.pack(fill="both", expand=True)
        self.title("PWF Auth - License Information")

    def _set_login_busy(self, busy: bool) -> None:
        self._logging_in = busy
        self.license_entry.configure(state="disabled" if busy else "normal")
        self.login_button.configure(
            state="disabled" if busy else "normal",
            text="Verifying..." if busy else "Sign In",
        )
        if busy:
            self.login_progress.place(x=42, y=341, width=416, height=4)
            self.login_progress.start(10)
        else:
            self.login_progress.stop()
            self.login_progress.place_forget()

    def _set_move_visible(self, visible: bool) -> None:
        if visible:
            self.move_frame.place(x=42, y=410, width=416, height=40)
        else:
            self.move_frame.place_forget()

    def _set_login_message(self, message: str, *, error: bool) -> None:
        self.login_status.configure(
            text=message,
            fg=COLORS["error"] if error else COLORS["muted_dark"],
        )

    def _copy_json(self) -> None:
        value = self.raw_json.get("1.0", "end-1c")
        if not value:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(value)
            self.update_idletasks()
            self.copy_button.configure(text="Copied ✓")
            if self._copy_reset_after:
                self.after_cancel(self._copy_reset_after)
            self._copy_reset_after = self.after(
                1600, lambda: self.copy_button.configure(text="Copy JSON")
            )
        except tk.TclError as exc:
            messagebox.showwarning("PWF Auth", f"Could not copy the JSON: {exc}")

    def _request_close(self) -> None:
        if self._closing:
            return
        client = self._client
        if client is None or not client.is_signed_in:
            self.destroy()
            return
        self._closing = True
        self.logout_button.configure(state="disabled")
        self.session_status.configure(text="Closing session...", fg=COLORS["warning"])
        threading.Thread(
            target=self._logout_worker,
            args=(client, True),
            daemon=True,
            name="pwfauth-close",
        ).start()


def main() -> None:
    app = PwfAuthApp()
    app.mainloop()


if __name__ == "__main__":
    main()
