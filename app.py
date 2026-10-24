"""SpotlightPy — launcher stile Spotlight per Windows.

- hotkey globale (default Ctrl+Shift+E) apre/chiude la finestra
- risultati immediati dall'indice locale SQLite + indice di Windows Search
- scansione in background delle cartelle non indicizzate (es. share di rete)
  con rotellina "Caricamento file non indicizzati in corso…"
- Invio / click = apri l'elemento (file o cartella)
- Ctrl+Shift+E / Ctrl+Invio = apri la cartella che lo contiene
- hotkey personalizzate che lanciano script con il percorso selezionato

Uso:  python app.py            (GUI normale)
      python app.py --smoke    (self-test: costruisce la UI ed esce)
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from contextlib import suppress
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont

import indexscope
import updater
from config import APP_NAME, DB_PATH, app_dir, load_config, save_config
from hotkeys import HotkeyManager, normalize_hotkey
from indexer import FileIndex, IndexerThread, LiveScanner
from linkinfo import describe as link_describe
from linkinfo import is_link
from query import is_empty as query_is_empty
from query import name_rank
from winsearch import WindowsSearch

LOG_PATH = os.path.join(app_dir(), "spotlightpy.log")
APP_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION = "1.27"


def log(msg: str) -> None:
    """Log su file: serve a capire i crash silenziosi di pythonw."""
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 512_000:
            os.replace(LOG_PATH, LOG_PATH + ".old")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{stamp}  {msg}\n")
    except Exception:  # noqa: BLE001 - il log non deve mai rompere l'app
        return

# ----------------------------------------------------------------------------
# Tema
# ----------------------------------------------------------------------------
C = {
    "bg": "#14161b",
    "bg2": "#1b1e25",
    "bg3": "#232732",
    "fg": "#e8ebf1",
    "dim": "#8b93a3",
    "accent": "#4d8dff",
    "sel": "#2c4a80",
    "border": "#2b3140",
    "warn": "#e0a33e",
    "err": "#e0605a",
}

SPINNER = "◐◓◑◒"
MAX_ROWS = 11

# tasti che NON cambiano il testo: il loro KeyRelease non deve far ripartire
# la ricerca (altrimenti ogni freccia in giu' azzera la selezione)
_NON_TEXT_KEYS = {
    "Up", "Down", "Left", "Right", "Home", "End", "Prior", "Next",
    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
    "Win_L", "Win_R", "Caps_Lock", "Num_Lock", "Escape", "Return",
    "KP_Enter", "Tab", "Insert", "F1", "F2",
    "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
}


def _dpi_scale() -> float:
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        return max(1.0, dpi / 96.0)
    except Exception:  # noqa: BLE001 - fallback se l'API non c'e'
        return 1.0


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else "…" + text[-(limit - 1):]


def _shell_exec(target: str, params: str | None = None) -> None:
    """Apre un file/cartella con l'applicazione associata (ShellExecuteW)."""
    rc = ctypes.windll.shell32.ShellExecuteW(None, "open", target, params, None, 1)
    if rc <= 32:
        raise OSError(f"ShellExecuteW ha restituito {rc} per {target!r}")


def _shell_open(path: str) -> None:
    _shell_exec(path)


def launch(cmdline: str) -> None:
    """Esegue la command line dell'utente come l'ha scritta.

    Si passa una *stringa* (non una lista) a Popen: cosi' Windows la riceve
    verbatim, senza il re-quoting che con `cmd.exe /c` faceva arrivare a
    PowerShell `-File` un argomento che iniziava con un doppio apice
    (errore "Illegal characters in path").

    Le variabili d'ambiente sono espanse qui (`%LOCALAPPDATA%`, `%USERPROFILE%`,
    ...): senza shell il sistema non le espanderebbe.

    Se il primo token non e' un eseguibile (script .bat/.cmd o comando interno
    di cmd) si riprova via cmd.exe. In quel caso serve `/s` + virgolette:
    `cmd /s /c "..."` toglie solo il primo e l'ultimo apice e lascia intatto
    il resto (altrimenti `cmd /c "C:\\a b\\x.exe" "arg"` si sfasciarebbe).
    """
    line = os.path.expandvars(cmdline)
    try:
        subprocess.Popen(line, close_fds=True)  # noqa: S603 - comando utente
    except OSError:
        subprocess.Popen(f'cmd.exe /s /c "{line}"', close_fds=True)  # noqa: S603


class _RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                ("right", wt.LONG), ("bottom", wt.LONG)]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", _RECT), ("rcWork", _RECT),
                ("dwFlags", wt.DWORD), ("szDevice", wt.WCHAR * 32)]


def monitor_at(x: int, y: int) -> tuple[str, tuple[int, int, int, int]]:
    """Monitor che contiene il punto (x, y): nome device + area di lavoro."""
    user32 = ctypes.windll.user32
    try:
        user32.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p,
                                          ctypes.POINTER(_MONITORINFOEXW)]
        user32.GetMonitorInfoW.restype = ctypes.c_bool
        hmon = user32.MonitorFromPoint(wt.POINT(int(x), int(y)), 2)  # NEAREST
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if hmon and user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcWork
            return str(info.szDevice), (r.left, r.top, r.right, r.bottom)
    except Exception:  # noqa: BLE001 - fallback: schermo primario
        return "", (0, 0, ctypes.windll.user32.GetSystemMetrics(0),
                    ctypes.windll.user32.GetSystemMetrics(1))
    user32 = ctypes.windll.user32
    return "", (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


def cursor_pos() -> tuple[int, int]:
    pt = wt.POINT()
    try:
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    except Exception:  # noqa: BLE001 - in dubbio, angolo alto a sinistra
        return (0, 0)
    return (pt.x, pt.y)


def _hwnd(root: tk.Misc) -> int:
    """Handle della finestra Toplevel (root della gerarchia)."""
    try:
        hwnd = root.winfo_id()
        owner = ctypes.windll.user32.GetAncestor(hwnd, 2)  # GA_ROOT
        return int(owner or hwnd)
    except Exception:  # noqa: BLE001
        return 0


def _foreground() -> int:
    try:
        return int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:  # noqa: BLE001
        return 0


# ----------------------------------------------------------------------------
# Widget: campo hotkey con cattura della combinazione
# ----------------------------------------------------------------------------
class HotkeyEntry(tk.Entry):
    def __init__(self, master, value: str = "", **kw):
        self.var = tk.StringVar(value=value)
        super().__init__(master, textvariable=self.var, state="readonly",
                         readonlybackground=C["bg2"], fg=C["fg"],
                         justify="center", width=20, **kw)
        self.bind("<KeyPress>", self._on_key)
        self.bind("<Button-1>", lambda e: self.focus_set())

    def get_hotkey(self) -> str:
        return self.var.get().strip()

    def set_hotkey(self, value: str):
        self.var.set(value or "")

    def _on_key(self, event):
        keysym = (event.keysym or "").lower()
        if keysym in ("control_l", "control_r", "shift_l", "shift_r",
                      "alt_l", "alt_r", "caps_lock", "win_l", "win_r",
                      "num_lock", "super_l", "super_r"):
            return "break"
        mods = []
        state = event.state
        if state & 0x0004:
            mods.append("ctrl")
        if state & 0x0001:
            mods.append("shift")
        if state & 0x20000:
            mods.append("alt")

        alias = {
            "return": "enter", "escape": "esc", "prior": "pageup",
            "next": "pagedown", "del": "delete", "ins": "insert",
        }
        key = alias.get(keysym, keysym)
        shift_map = {
            "exclam": "1", "quotedbl": "2", "sterling": "3", "dollar": "4",
            "percent": "5", "ampersand": "6", "slash": "7", "parenleft": "8",
            "parenright": "9", "asterisk": "8", "plus": "plus", "minus": "minus",
            "comma": "comma", "period": "period", "eacute": "e", "egrave": "egrave",
            "agrave": "agrave", "ograve": "ograve", "ugrave": "ugrave",
            "igrave": "igrave",
        }
        key = shift_map.get(key, key)
        if len(key) == 1:
            key = key.lower()
        if not mods:
            self.var.set("")
            return "break"
        spec = "+".join(mods + [key])
        try:
            spec = normalize_hotkey(spec)
        except ValueError:
            return "break"
        self.var.set(spec)
        return "break"


# ----------------------------------------------------------------------------
# App principale
# ----------------------------------------------------------------------------
class SpotlightApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.report_callback_exception = self._tk_error
        self.cfg = load_config()
        self.db = FileIndex(DB_PATH)
        self.winsearch = WindowsSearch()
        self.hotkeys = HotkeyManager()

        self.events: queue.Queue = queue.Queue()   # scansioni + indice
        self.results: list[dict] = []
        self.seen: set[str] = set()
        self.query_now = ""
        self.sel = 0
        self.offset = 0
        self.row_widgets: list[tuple] = []
        self.scan: LiveScanner | None = None
        self.scan_id = 0
        self.busy_scan = False
        self.busy_index = False
        self.busy_win = False
        self._pending = False
        self.status_text = ""
        self.status_kind = "dim"
        self._spin = 0
        self._debounce = None
        self._settings_open = False
        self._tmp_indexer = None
        self._quitting = False
        self._suppress_hide = False
        self._tick_count = 0
        self.win_info: dict = {}
        self.filter = self.cfg.get("filter", "all")
        if self.filter not in self._filter_modes():
            self.filter = "all"
        self.view: list[dict] = []
        self.source_colors = {
            "pc": C["accent"],        # indice di Windows Search (blu)
            "index": C["dim"],        # voce orfana dell'indice locale (grigio)
            "net": C["warn"],         # cartelle personalizzate di rete (ambra)
            "excl": "#a78bfa",        # cartelle escluse dall'indice di Windows (viola)
        }
        self.root_kinds: dict[str, str] = {}
        self._rebuild_root_kinds()
        self._sync_winsearch_flags()

        self.scale = _dpi_scale()
        self._build_ui()
        self._apply_hotkeys()
        if self.cfg.get("index_on_startup"):
            self.start_indexer()

        self.root.after(60, self._poll)
        self.root.after(120, self._tick)

    # ------------------------------------------------------------------ UI
    @staticmethod
    def _tk_error(exc_type, exc, tb):
        """Con pythonw gli errori nelle callback Tk non si vedono: li loggo."""
        log("ERRORE CALLBACK TK:\n" + "".join(
            traceback.format_exception(exc_type, exc, tb)))

    def _build_ui(self):
        r = self.root
        r.withdraw()
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.configure(bg=C["border"])

        w = int(760 * self.scale)
        h = int(520 * self.scale)
        sw = r.winfo_screenwidth()
        sh = r.winfo_screenheight()
        x = (sw - w) // 2
        y = max(20, int(sh * 0.16))
        pos = self.cfg.get("window_pos")
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            try:
                px, py = int(pos[0]), int(pos[1])
            except (TypeError, ValueError):
                px, py = x, y
            if -40 <= px <= sw - 120 and -10 <= py <= sh - 120:
                x, y = px, py
        r.geometry(f"{w}x{h}+{x}+{y}")
        self.win_w, self.win_h = w, h
        self._drag_off: tuple[int, int] | None = None
        self._shown_at = 0.0

        outer = tk.Frame(r, bg=C["bg"])
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        self.font_input = tkfont.Font(family="Segoe UI", size=15)
        self.font_row = tkfont.Font(family="Segoe UI", size=10)
        self.font_row_b = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.font_small = tkfont.Font(family="Segoe UI", size=8)
        self.font_icon = tkfont.Font(family="Segoe UI Emoji", size=11)

        # ---- riga di input ----
        top = tk.Frame(outer, bg=C["bg2"])
        top.pack(fill="x")

        tk.Label(top, text="⌕", bg=C["bg2"], fg=C["accent"],
                 font=("Segoe UI", 18)).pack(side="left", padx=(14, 6))

        self.entry = tk.Entry(top, bg=C["bg2"], fg=C["fg"], insertbackground=C["fg"],
                              relief="flat", font=self.font_input, bd=0)
        self.entry.pack(side="left", fill="x", expand=True, pady=int(14 * self.scale))
        self.entry.bind("<KeyRelease>", self._on_query_change)
        self.entry.bind("<Down>", lambda e: self._move(1))
        self.entry.bind("<Up>", lambda e: self._move(-1))
        self.entry.bind("<Return>", self._on_enter)
        self.entry.bind("<KP_Enter>", self._on_enter)
        self.entry.bind("<Control-Return>", lambda e: self._activate(reveal=True))
        self.entry.bind("<Control-Shift-E>", lambda e: self._activate(reveal=True))
        self.entry.bind("<Control-Shift-e>", lambda e: self._activate(reveal=True))
        self.entry.bind("<Escape>", lambda e: self.hide())
        self.entry.bind("<Control-comma>", lambda e: self.open_settings())

        self.spin_lbl = tk.Label(top, text="", bg=C["bg2"], fg=C["accent"],
                                 font=("Segoe UI", 13), width=2)
        self.spin_lbl.pack(side="right", padx=(0, 4))

        self.gear = tk.Label(top, text="⚙", bg=C["bg2"], fg=C["dim"],
                             font=("Segoe UI", 13), cursor="hand2")
        self.gear.pack(side="right", padx=(0, 12))
        self.gear.bind("<Button-1>", lambda e: self.open_settings())

        # filtro: Tutti / Solo file / Solo cartelle (click o Ctrl+T)
        self.filter_lbl = tk.Label(top, text=self._filter_text(), bg=C["bg2"],
                                   fg=C["dim"], font=self.font_small,
                                   cursor="hand2")
        self.filter_lbl.pack(side="right", padx=(0, 10))
        self.filter_lbl.bind("<Button-1>", lambda e: self._cycle_filter())
        self.entry.bind("<Control-t>", self._on_toggle_filter)

        # ---- riga di stato ----
        self.status_frame = tk.Frame(outer, bg=C["bg"])
        self.status_frame.pack(fill="x")
        self.status_lbl = tk.Label(self.status_frame, text="", bg=C["bg"],
                                   fg=C["dim"], font=self.font_small, anchor="w")
        self.status_lbl.pack(side="left", padx=16, pady=(4, 0))

        # ---- risultati ----
        self.rows_frame = tk.Frame(outer, bg=C["bg"])
        self.rows_frame.pack(fill="both", expand=True, pady=(6, 4))

        # ---- footer ----
        footer = tk.Frame(outer, bg=C["bg2"])
        footer.pack(fill="x", side="bottom")
        self.hint_lbl = tk.Label(footer, text="", bg=C["bg2"], fg=C["dim"],
                                 font=self.font_small, anchor="w", justify="left")
        self.hint_lbl.pack(side="left", padx=14, pady=6)

        self._update_hints()

        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            r.bind(seq, self._on_wheel)
        r.bind("<Escape>", lambda e: self.hide())
        r.bind("<FocusOut>", self._on_focus_out)

        # trascinamento della finestra (drag & drop) dalle zone "vuote"
        for wdg in (outer, top, self.status_frame, footer, self.rows_frame,
                    self.status_lbl, self.hint_lbl):
            self._bind_drag(wdg)

    # ------------------------------------------------------- drag della finestra
    def _bind_drag(self, widget):
        widget.bind("<Button-1>", self._drag_start, add="+")
        widget.bind("<B1-Motion>", self._drag_move, add="+")
        widget.bind("<ButtonRelease-1>", self._drag_end, add="+")

    def _drag_start(self, event):
        self._drag_off = (event.x_root - self.root.winfo_x(),
                          event.y_root - self.root.winfo_y())

    def _drag_move(self, event):
        if self._drag_off is None:
            return
        x = event.x_root - self._drag_off[0]
        y = event.y_root - self._drag_off[1]
        self.root.geometry(f"+{x}+{y}")

    def _drag_end(self, _event=None):
        if self._drag_off is None:
            return
        self._drag_off = None
        pos = [self.root.winfo_x(), self.root.winfo_y()]
        self.cfg["window_pos"] = pos
        # posizione distinta per ogni schermo (chiave = device del monitor)
        device, _area = monitor_at(pos[0] + int(40 * self.scale),
                                   pos[1] + int(10 * self.scale))
        by_monitor = dict(self.cfg.get("window_pos_by_monitor") or {})
        by_monitor[device] = pos
        self.cfg["window_pos_by_monitor"] = by_monitor
        with suppress(Exception):
            save_config(self.cfg)

    def _update_hints(self):
        parts = ["Invio / click: apri", "Ctrl+Shift+E: apri in Explorer",
                 "↑↓: naviga", "Ctrl+T: filtro", "Esc: chiudi",
                 "Ctrl+,: impostazioni"]
        for s in self.cfg.get("scripts", []):
            if s.get("hotkey"):
                parts.append(f"{s['hotkey'].upper()}: {s.get('name') or 'script'}")
        if self.cfg.get("quit_hotkey"):
            parts.append(f"{self.cfg['quit_hotkey'].upper()}: esci")
        main = self._main_hotkey()
        if main:
            parts.insert(0, f"{main.upper()}: apri/chiudi")
        self.hint_lbl.config(text="   ·   ".join(parts))

    # ------------------------------------------------------- visibilita'
    # ------------------------------------------------------- posizionamento
    def _place_window(self):
        """Posiziona la finestra sullo schermo attivo (quello del cursore),
        riusando l'ultima posizione salvata per *quello* schermo."""
        cx, cy = cursor_pos()
        device, (left, top, right, bottom) = monitor_at(cx, cy)
        w, h = self.win_w, self.win_h
        saved = (self.cfg.get("window_pos_by_monitor") or {}).get(device)
        x: int | None = None
        y: int | None = None
        if isinstance(saved, (list, tuple)) and len(saved) == 2:
            try:
                sx, sy = int(saved[0]), int(saved[1])
            except (TypeError, ValueError):
                sx = sy = -1        # valori non validi: fuori range, si ricentra
            if (left - 40 <= sx <= right - 120
                    and top - 10 <= sy <= bottom - 120):
                x, y = sx, sy
        if x is None or y is None:
            x = left + max(0, (right - left - w) // 2)
            y = top + max(20, int((bottom - top) * 0.16))
        with suppress(Exception):
            self.root.geometry(f"{w}x{h}+{x}+{y}")

    def show(self):
        self._shown_at = time.time()
        self._suppress_hide = False
        self._place_window()
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.focus_force()
        self.entry.focus_force()
        self.entry.select_range(0, "end")
        hwnd = _hwnd(self.root)
        if hwnd and _foreground() != hwnd:
            with suppress(Exception):
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        # ridisegna sempre: cosi' torna selezionato l'ultimo elemento scelto
        if self.view and self.sel >= len(self.view):
            self.sel = len(self.view) - 1
        self._render()

    def to_back(self):
        """Manda la finestra in secondo piano senza chiuderla."""
        with suppress(Exception):
            self.root.attributes("-topmost", False)
        self._suppress_hide = True
        with suppress(Exception):
            self.root.lower()

    def hide(self):
        if self._settings_open:
            return
        self.root.withdraw()

    def toggle(self):
        if self.root.state() == "withdrawn":
            self.show()
        else:
            self.hide()

    def quit_app(self):
        """Chiude davvero il processo (le hotkey vengono deregistrate)."""
        log("uscita")
        self._quitting = True
        with suppress(Exception):
            self.hotkeys.stop()
        with suppress(Exception):
            self.root.destroy()

    def restart_app(self):
        """Riavvia l'app (dopo un aggiornamento)."""
        log("riavvio richiesto")
        prog = sys.executable
        args: list[str] = []
        if updater.is_frozen():
            pass
        else:
            args = [os.path.join(APP_DIR, "app.py")]
            if prog.lower().endswith("python.exe"):
                candidate = prog[: -len("python.exe")] + "pythonw.exe"
                if os.path.exists(candidate):
                    prog = candidate
        with suppress(Exception):
            subprocess.Popen([prog, *args], cwd=APP_DIR)
        self.quit_app()

    def _start_show_watcher(self, handle):
        """Aspetta il segnale delle istanze successive: "mostrati"."""
        def run():
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            kernel32.WaitForSingleObject.restype = ctypes.c_uint32
            while not self._quitting:
                if kernel32.WaitForSingleObject(handle, 500) == 0:
                    log("richiesta di mostra da un'altra istanza")
                    self.events.put(("show",))

        threading.Thread(target=run, daemon=True, name="show-watcher").start()

    def _on_focus_out(self, _event=None):
        if not self.cfg.get("hide_on_focus_loss") or self._settings_open:
            return
        self.root.after(200, self._maybe_hide)

    def _maybe_hide(self):
        """Nasconde solo se il focus e' andato davvero a un'altra finestra:
        evita che la finestra sparisca subito dopo essere stata aperta."""
        if self._settings_open or self._suppress_hide:
            return
        if self.root.state() == "withdrawn":
            return
        if time.time() - self._shown_at < 0.7:      # grazia dopo l'apertura
            return
        hwnd = _hwnd(self.root)
        fg = _foreground()
        if not hwnd or not fg:
            return
        if fg == hwnd or int(ctypes.windll.user32.GetAncestor(fg, 2) or 0) == hwnd:
            return
        self.hide()

    # ------------------------------------------------------- hotkeys
    RESERVED_LOCAL = "ctrl+shift+e"

    def _main_hotkey(self) -> str:
        """Hotkey globale che apre/chiude la finestra ("" = disabilitata).

        ctrl+shift+e e' riservato alla finestra: se nel vecchio config c'e'
        ancora quello, viene considerato disabilitato."""
        hk = (self.cfg.get("hotkey") or "").strip().lower()
        if hk == self.RESERVED_LOCAL:
            return ""
        return hk

    def _apply_hotkeys(self):
        bindings = {}
        main = self._main_hotkey()
        if main:
            bindings["__main__"] = main
        else:
            log("hotkey principale disabilitata: la finestra si apre dal bat/exe")
        quit_hk = self.cfg.get("quit_hotkey") or ""
        if quit_hk:
            bindings["__quit__"] = quit_hk
        for i, s in enumerate(self.cfg.get("scripts", [])):
            hk = (s.get("hotkey") or "").strip()
            if hk:
                bindings[f"script:{i}"] = hk
        errors = self.hotkeys.start(bindings)
        if errors:
            log("hotkey non registrate: " + " | ".join(errors))
            self.set_status("Hotkey: " + " | ".join(errors), "warn")
        else:
            log("hotkey registrate: " + ", ".join(f"{k}={v}" for k, v in bindings.items()))
        self._update_hints()

    def _poll_hotkeys(self):
        while True:
            try:
                name = self.hotkeys.events.get_nowait()
            except queue.Empty:
                return
            if name == "__quit__":
                log("quit da hotkey")
                self.quit_app()
                return
            if name == "__main__":
                # solo apri/chiudi: la cartella contenitrice e' Ctrl+Shift+E
                # premuto *dentro* la finestra
                self.toggle()
            elif name.startswith("script:"):
                try:
                    idx = int(name.split(":", 1)[1])
                    script = self.cfg["scripts"][idx]
                except (ValueError, IndexError, KeyError):
                    continue
                self._run_script(script, self._selected_path())

    # ------------------------------------------------------- ricerca
    def _on_query_change(self, event=None):
        keysym = getattr(event, "keysym", "") if event is not None else ""
        if keysym in _NON_TEXT_KEYS:
            return
        text = self.entry.get().strip()
        if text == self.query_now and self._debounce is None:
            return
        if self._debounce:
            with suppress(Exception):
                self.root.after_cancel(self._debounce)
        self._pending = True
        self._debounce = self.root.after(130, self._run_search)

    def _run_search(self):
        self._debounce = None
        self._pending = False
        q = self.entry.get().strip()
        self.query_now = q
        self._stop_scan()
        self.sel = 0
        self.offset = 0
        self.results = []
        self.view = []
        self.seen = set()

        if query_is_empty(q):
            self.busy_scan = False
            self.set_status("")
            self._render()
            return

        # 1) risultati istantanei dall'indice locale (gia' scansionato)
        self._merge(self.db.search(q, limit=self.cfg.get("max_results", 120)), "index")
        self._render()

        # 2) indice di Windows (thread separato; con i jolly puo' richiedere
        #    qualche secondo, quindi mostriamo la rotellina)
        if self.cfg.get("win_search") and len(q) >= 2:
            self.busy_win = True
            threading.Thread(target=self._win_bg, args=(q,), daemon=True).start()

        # 3) scansione "viva" delle cartelle non indicizzate
        roots = [p for p in self.cfg.get("paths", []) if p]
        if self.cfg.get("live_scan") and roots:
            self.scan_id += 1
            self.scan = LiveScanner(self.db, roots, self.cfg.get("excludes"),
                                    q, self.events, self.scan_id)
            self.busy_scan = True
            self.set_status("Caricamento file non indicizzati in corso…", "accent")
            self.scan.start()
        else:
            self.busy_scan = False

    def _sync_winsearch_flags(self):
        """Passa le opzioni delle Impostazioni all'istanza di WindowsSearch."""
        self.winsearch.content_search = bool(
            self.cfg.get("win_content_search", True))
        self.winsearch.path_search = bool(
            self.cfg.get("win_path_search", True))

    def _win_bg(self, q):
        try:
            items, info = self.winsearch.search(
                q, limit=self.cfg.get("win_search_limit", 40))
        except Exception as exc:  # noqa: BLE001 - se Windows Search fallisce si prosegue
            items = []
            info = {"strategies": [], "count": 0,
                    "error": f"{type(exc).__name__}: {exc}"}
        self.events.put(("win", q, items, info))

    def _stop_scan(self):
        if self.scan is not None and self.scan.is_alive():
            self.scan.stop_event.set()
        self.scan = None
        self.busy_scan = False

    def _rebuild_root_kinds(self):
        """Classifica le cartelle personalizzate: 'net' (rete) o 'excl'
        (locale non coperta dall'indice di Windows). Serve per i colori."""
        stored = dict(self.cfg.get("path_kinds") or {})
        kinds: dict[str, str] = {}
        for path in self.cfg.get("paths", []):
            key = os.path.normpath(path).lower()
            kind = stored.get(key)
            if kind not in ("net", "excl"):
                kind = "net" if indexscope.is_network(path) else "excl"
            kinds[key] = kind
        self.root_kinds = kinds

    def _classify(self, path: str) -> str:
        """Tipo della cartella personalizzata che contiene il percorso."""
        low = os.path.normpath(str(path or "")).lower()
        best = ""
        best_len = 0
        for root, kind in self.root_kinds.items():
            if (low == root or low.startswith(root + "\\")) and len(root) > best_len:
                best, best_len = kind, len(root)
        return best

    def _merge(self, items, source):
        added = False
        links_on = bool(self.cfg.get("search_links", True))
        for it in items:
            path = it.get("path")
            if not path:
                continue
            if not links_on and is_link(path):
                continue
            # i risultati dell'indice locale / della scansione prendono il colore
            # della cartella personalizzata da cui provengono
            if it.get("source") in (None, "index", "net"):
                kind = self._classify(path)
                if kind:
                    it["source"] = kind
                elif not it.get("source"):
                    it["source"] = source
            key = path.lower()
            if key in self.seen:
                continue
            self.seen.add(key)
            it.setdefault("dir", path.rsplit("\\", 1)[0] if "\\" in path else path)
            it["source"] = it.get("source") or source
            self.results.append(it)
            added = True
        if added:
            self._sort_results()
        return added

    def _sort_results(self):
        q = self.query_now.lower()

        def score(it):
            n = it.get("name") or ""
            return (name_rank(n, q), len(n), it["path"].lower())

        self.results.sort(key=score)
        maxr = self.cfg.get("max_results", 120)
        if len(self.results) > maxr:
            dropped = self.results[maxr:]
            self.results = self.results[:maxr]
            for it in dropped:
                self.seen.discard(it["path"].lower())
        if self.sel >= len(self.results):
            self.sel = max(0, len(self.results) - 1)
        self._apply_filter()

    # ------------------------------------------------------- rendering
    # ------------------------------------------------------- filtro risultati
    FILTER_LABEL = {"all": "Tutti", "files": "Solo file",
                    "dirs": "Solo cartelle", "text": "Solo testo"}

    def _filter_modes(self) -> tuple[str, ...]:
        """Filtri disponibili: «Solo testo» solo se la ricerca nel contenuto è attiva."""
        modes = ["all", "files", "dirs"]
        if self.cfg.get("win_content_search", True):
            modes.append("text")
        return tuple(modes)

    def _filter_text(self) -> str:
        return self.FILTER_LABEL.get(self.filter, "Tutti")

    def _on_toggle_filter(self, _event=None):
        self._cycle_filter()
        return "break"

    def _cycle_filter(self):
        modes = self._filter_modes()
        try:
            i = modes.index(self.filter)
        except ValueError:
            i = -1
        self.filter = modes[(i + 1) % len(modes)]
        self.cfg["filter"] = self.filter
        with suppress(Exception):
            save_config(self.cfg)
        with suppress(Exception):
            self.filter_lbl.config(text=self._filter_text())
        self._apply_filter()
        self.sel = 0
        self.offset = 0
        self._render()
        self.set_status(f"Filtro: {self._filter_text()} "
                        f"({len(self.view)} di {len(self.results)})", "accent")

    def refresh_filter(self):
        """Riallinea il filtro dopo un cambio di impostazioni."""
        if not self.cfg.get("win_content_search", True):
            # il toggle del testo e' stato spento: via i match gia' in lista
            self.results = [r for r in self.results if r.get("match") != "testo"]
        if self.filter not in self._filter_modes():
            self.filter = "all"
            self.cfg["filter"] = "all"
        with suppress(Exception):
            self.filter_lbl.config(text=self._filter_text())
        self._apply_filter()
        self.sel = 0
        self.offset = 0
        self._render()

    def _apply_filter(self):
        mode = self.filter
        if mode not in self._filter_modes():
            mode = "all"
        if mode == "files":
            # solo nomi di file: esclude le cartelle e i match trovati nel testo
            self.view = [r for r in self.results
                         if not r.get("is_dir") and r.get("match") != "testo"]
        elif mode == "dirs":
            self.view = [r for r in self.results if r.get("is_dir")]
        elif mode == "text":
            self.view = [r for r in self.results if r.get("match") == "testo"]
        else:
            self.view = list(self.results)
        if self.view and self.sel >= len(self.view):
            self.sel = len(self.view) - 1

    # ------------------------------------------------------- rendering
    def _fit_name(self, item) -> str:
        """Nome da mostrare: estensione sempre visibile, troncamento con …
        in mezzo se troppo lungo (es. "contratto molto lungo …2024.pdf")."""
        name = str(item.get("name") or "")
        is_dir = bool(item.get("is_dir"))
        if not is_dir:
            ext = os.path.splitext(str(item.get("path") or ""))[1]
            if ext and not name.lower().endswith(ext.lower()):
                name += ext
        limit = 52
        if len(name) <= limit:
            return name
        if is_dir:
            return name[: limit - 1] + "…"
        root, ext = os.path.splitext(name)
        keep = limit - len(ext) - 1
        if keep < 8:
            return name[: limit - 1] + "…"
        return root[:keep] + "…" + ext

    def _render(self):
        for w in self.rows_frame.winfo_children():
            w.destroy()
        self.row_widgets = []

        if not self.view:
            if self._pending or self.busy_win or self.busy_scan:
                msg = "Ricerca in corso…"
            elif not self.query_now:
                msg = ("Scrivi per cercare…   "
                       "(* = uno o più caratteri, es. scaffalatur*ord*23440)")
            elif self.results:
                msg = (f"Nessun risultato con il filtro «{self._filter_text()}» "
                       f"({len(self.results)} trovati)")
            else:
                msg = "Nessun risultato"
            tk.Label(self.rows_frame, text=msg, bg=C["bg"], fg=C["dim"],
                     font=self.font_row).pack(pady=24)
            return

        total = len(self.view)
        self.offset = max(0, min(self.offset, max(0, total - MAX_ROWS)))
        visible = self.view[self.offset:self.offset + MAX_ROWS]
        # larghezza/altezza in pixel dell'icona: deve contenere anche la freccia
        # dei .lnk; senza altezza esplicita il contenitore collasserebbe a 0 px
        icon_w = self.font_icon.measure("\U0001F4C1\u2197") + int(10 * self.scale)
        icon_h = self.font_icon.metrics("linespace") + int(6 * self.scale)

        for i, item in enumerate(visible):
            abs_idx = self.offset + i
            f = tk.Frame(self.rows_frame, bg=C["bg"], cursor="hand2")
            f.pack(fill="x", padx=8, pady=1)

            source = str(item.get("source") or "index")
            # tipo: cartella o file (per i .lnk vale il target)
            info = link_describe(item["path"])
            item.update(info)
            link = info["is_link"]
            is_dir = bool(item.get("is_dir")) or bool(info["link_is_dir"])
            icon = "📁" if is_dir else "📄"
            if link:
                icon += "↗"
            color = self.source_colors.get(source, C["accent"])
            # contenitore a larghezza fissa (pixel): l'icona doppia non si taglia
            # e i nomi restano allineati su tutte le righe
            box = tk.Frame(f, bg=C["bg"], width=icon_w, height=icon_h)
            box.pack(side="left", padx=(6, 2))
            box.pack_propagate(False)
            lbl_i = tk.Label(box, text=icon, bg=C["bg"], fg=color,
                             font=self.font_icon, anchor="w")
            lbl_i.pack(side="left", fill="both")

            lbl_n = tk.Label(f, text=self._fit_name(item), bg=C["bg"], fg=C["fg"],
                             font=self.font_row_b, anchor="w")
            lbl_n.pack(side="left")

            avail = max(20, int((self.win_w - 210) / (8 * self.scale / 1.4)))
            if link and info["link_target"]:
                dir_text = "→ " + info["link_target"]
            else:
                dir_text = item["dir"]
                if source == "net":
                    dir_text = "rete · " + dir_text
            if item.get("match") == "testo":
                dir_text = "testo · " + dir_text
            lbl_d = tk.Label(f, text=_shorten(dir_text, int(avail)),
                             bg=C["bg"], fg=C["dim"], font=self.font_row, anchor="e")
            lbl_d.pack(side="right", padx=(8, 6))

            for w in (f, box, lbl_i, lbl_n, lbl_d):
                w.bind("<Button-1>", lambda e, i=abs_idx: self._click_row(i))
                w.bind("<Button-3>", lambda e, i=abs_idx: self._context_menu(e, i))
                w.bind("<Enter>", lambda e, i=abs_idx: self._hover(i))
            self.row_widgets.append((abs_idx, f, box, lbl_i, lbl_n, lbl_d))

        self._paint_selection()

    def _paint_selection(self):
        for abs_idx, f, box, lbl_i, lbl_n, lbl_d in self.row_widgets:
            if abs_idx == self.sel:
                bg, fg = C["sel"], "#ffffff"
            else:
                bg, fg = C["bg"], C["fg"]
            f.config(bg=bg)
            box.config(bg=bg)
            lbl_i.config(bg=bg)
            lbl_n.config(bg=bg, fg=fg)
            lbl_d.config(bg=bg, fg="#b9c3d6" if abs_idx == self.sel else C["dim"])

    def _hover(self, idx):
        if idx != self.sel:
            self._select(idx, scroll=False)

    def _select(self, idx, scroll=True):
        if not self.view:
            return
        idx = max(0, min(idx, len(self.view) - 1))
        self.sel = idx
        if scroll:
            if idx < self.offset:
                self.offset = idx
                self._render()
                return
            if idx >= self.offset + MAX_ROWS:
                self.offset = idx - MAX_ROWS + 1
                self._render()
                return
        self._paint_selection()

    def _move(self, delta):
        if not self.view:
            return "break"
        self._select(self.sel + delta)
        return "break"

    def _on_wheel(self, event):
        if not self.view:
            return
        up = getattr(event, "delta", 0) > 0 or getattr(event, "num", 0) == 4
        step = -1 if up else 1
        new_off = max(0, min(self.offset + step * 2,
                             max(0, len(self.view) - MAX_ROWS)))
        if new_off != self.offset:
            self.offset = new_off
            self._render()

    def _click_row(self, idx):
        self.sel = idx
        self._activate(reveal=False)

    def _selected_item(self):
        if 0 <= self.sel < len(self.view):
            return self.view[self.sel]
        return None

    def _selected_path(self):
        it = self._selected_item()
        if it:
            return it["path"]
        typed = self.entry.get().strip().strip('"')
        if typed and os.path.exists(typed):
            return typed
        return None

    def _on_enter(self, event):
        reveal = bool(event.state & 0x0004)   # ctrl
        self._activate(reveal=reveal)
        return "break"

    # ------------------------------------------------------- azioni
    def _activate(self, reveal=False):
        """Apre l'elemento selezionato (file o cartella) con l'app associata,
        oppure la cartella che lo contiene (con l'elemento selezionato)."""
        it = self._selected_item()
        if it is None:
            self.set_status("Nessun elemento selezionato", "warn")
            return
        path = it["path"]
        self.hide()
        if reveal:
            self.open_folder(path)
        else:
            self.open_file(path)

    def open_file(self, path):
        """File -> app associata; cartella -> Esplora file sulla cartella."""
        try:
            _shell_open(path)
        except Exception as exc:  # noqa: BLE001 - qualunque errore va mostrato
            self.set_status(f"Errore apertura: {exc}", "err")

    def open_folder(self, path):
        """Apre la cartella che contiene l'elemento, con l'elemento selezionato."""
        try:
            _shell_exec("explorer.exe", f'/select,"{path}"')
        except Exception as exc:  # noqa: BLE001 - qualunque errore va mostrato
            self.set_status(f"Errore apertura cartella: {exc}", "err")

    def _run_script(self, script: dict, path: str | None):
        cmd = (script.get("command") or "").strip()
        if not cmd:
            self.set_status("Script senza comando", "warn")
            return
        if not path:
            self.set_status("Nessun elemento selezionato per lo script", "warn")
            return
        quoted = f'"{path}"'
        if "{path}" in cmd:
            cmdline = cmd.replace("{path}", quoted)
        elif "{file}" in cmd:
            cmdline = cmd.replace("{file}", quoted)
        elif "%path%" in cmd:
            cmdline = cmd.replace("%path%", path)
        else:
            cmdline = f"{cmd} {quoted}"
        if script.get("keep_open"):
            # impostazione del singolo script: resta aperta, dietro le altre
            self.to_back()
        else:
            self.hide()
        try:
            log(f"script {script.get('name')!r}: {cmdline}")
            launch(cmdline)
        except Exception as exc:  # noqa: BLE001 - qualunque errore va mostrato
            log(f"errore script: {type(exc).__name__}: {exc}")
            self.set_status(f"Errore script: {exc}", "err")

    def _script_label(self, script: dict) -> str:
        label = script.get("name") or "script"
        if script.get("hotkey"):
            label += f"  [{script['hotkey'].upper()}]"
        return label

    def _build_context_menu(self, path: str) -> tk.Menu:
        """Menu del tasto destro: azioni sull'elemento + uno script per voce."""
        m = tk.Menu(self.root, tearoff=0, bg=C["bg2"], fg=C["fg"],
                    activebackground=C["accent"], activeforeground="#fff",
                    bd=0)
        m.add_command(label="Apri", command=lambda: self._activate(False))
        m.add_command(label="Apri in Explorer",
                      command=lambda: self._activate(True))
        m.add_command(label="Copia percorso", command=lambda: self._copy_path(path))
        m.add_separator()

        scripts = [s for s in self.cfg.get("scripts", []) if s.get("command")]
        if not scripts:
            m.add_command(label="Nessuno script: aggiungilo nelle impostazioni",
                          state="disabled")
            return m

        if len(scripts) <= 3:
            for s in scripts:
                m.add_command(label=self._script_label(s),
                              command=lambda sc=s: self._run_script(sc, path))
        else:
            # con molti script resto leggibile: sottomenu "Script (N)"
            sub = tk.Menu(m, tearoff=0, bg=C["bg2"], fg=C["fg"],
                          activebackground=C["accent"], activeforeground="#fff",
                          bd=0)
            for s in scripts:
                sub.add_command(label=self._script_label(s),
                                command=lambda sc=s: self._run_script(sc, path))
            m.add_cascade(label=f"Script ({len(scripts)})", menu=sub)
        return m

    def _context_menu(self, event, idx):
        self._select(idx)
        it = self._selected_item()
        if not it:
            return
        m = self._build_context_menu(it["path"])
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _copy_path(self, path):
        self.root.clipboard_clear()
        self.root.clipboard_append(path)
        self.set_status("Percorso copiato", "accent")

    # ------------------------------------------------------- stato
    def set_status(self, text: str, kind: str = "dim"):
        self.status_text = text or ""
        self.status_kind = kind
        self.status_lbl.config(text=self.status_text,
                               fg=C.get(kind, C["dim"]))

    def _tick(self):
        busy = self.busy_scan or self.busy_index or self.busy_win
        if busy:
            self._spin = (self._spin + 1) % len(SPINNER)
            self.spin_lbl.config(text=SPINNER[self._spin])
        else:
            self.spin_lbl.config(text="")
        if not busy and self.results and self.status_text.startswith(
                ("Caricamento file non indicizzati", "Indicizzazione")):
            self.set_status(f"{len(self.results)} risultati", "dim")
        # watchdog: se il thread delle hotkey e' morto, le ri-registra
        self._tick_count += 1
        if self._tick_count % 30 == 0 and not self.hotkeys.alive():
            log("thread hotkey morto: ri-registro")
            self._apply_hotkeys()
        self.root.after(110, self._tick)

    # ------------------------------------------------------- indice
    def start_indexer(self, clear_first=False):
        roots = [p for p in self.cfg.get("paths", []) if p]
        if not roots:
            return
        if self._tmp_indexer is not None and self._tmp_indexer.is_alive():
            self._tmp_indexer.stop_event.set()
        self.busy_index = True
        self.set_status("Indicizzazione in corso…", "accent")
        t = IndexerThread(self.db, roots, self.cfg.get("excludes"),
                          self.events, clear_first=clear_first)
        self._tmp_indexer = t
        t.start()

    def _poll(self):
        try:
            while True:
                ev = self.events.get_nowait()
                self._handle_event(ev)
        except queue.Empty:
            pass
        self._poll_hotkeys()
        self.root.after(70, self._poll)

    def _handle_event(self, ev):
        kind = ev[0]
        if kind == "show":
            self.show()
            return
        if kind == "win":
            q, items, info = ev[1], ev[2], ev[3]
            if q != self.query_now:
                return
            self.busy_win = False
            self.win_info = info
            if not self.winsearch.content_search:
                # niente corrispondenze nel testo se il toggle e' spento
                items = [i for i in items if i.get("match") != "testo"]
            log(f"ricerca {q!r}: windows={len(items)} "
                f"[{' '.join(info.get('strategies') or [])}] "
                f"errore={info.get('error')}")
            self._merge(items, "pc")
            # re-render sempre: se la query non trova nulla va tolto il
            # segnaposto "Ricerca in corso…" (e le righe della ricerca prima)
            self._render()
            detail = ", ".join(info.get("strategies") or []) or "nessuna risposta"
            if info.get("error"):
                self.set_status(f"Windows Search: errore — {info['error']}", "warn")
            else:
                self.set_status(f"{len(self.results)} risultati · Windows Search: {detail}",
                                "dim")
        elif kind == "scan_hits":
            sid, items = ev[1], ev[2]
            if sid != self.scan_id or not self.busy_scan:
                return
            if self._merge(items, "net"):
                self._render()
                self.set_status(f"Caricamento file non indicizzati in corso…  "
                                f"{len(self.results)} trovati", "accent")
        elif kind == "scan_pruned":
            if ev[1] == self.scan_id:
                log(f"indice ripulito durante la ricerca: {ev[2]} voci rimosse")
        elif kind == "scan_status":
            sid, text = ev[1], ev[2]
            if sid == self.scan_id:
                self.set_status(text, "accent")
        elif kind == "scan_done":
            sid, indexed = ev[1], ev[2]
            if sid == self.scan_id:
                self.busy_scan = False
                self.set_status(
                    f"Scansione completata · {indexed} file esaminati · "
                    f"{len(self.results)} risultati", "dim")
                self._render()
        elif kind == "scan_error":
            if ev[1] == self.scan_id:
                self.busy_scan = False
                self.set_status(f"Errore scansione: {ev[2]}", "err")
                self._render()
        elif kind == "idx":
            self.set_status(ev[1], "accent")
        elif kind == "idx_done":
            self.busy_index = False
            self.set_status(f"Indice aggiornato · {ev[1]} file · "
                            f"totale indice: {self.db.count()} file", "dim")
        elif kind == "idx_error":
            self.busy_index = False
            self.set_status(f"Errore indicizzazione: {ev[1]}", "err")

    # ------------------------------------------------------- impostazioni
    def open_settings(self):
        if self._settings_open:
            return
        self._settings_open = True
        SettingsWindow(self, on_close=self._settings_closed)

    def _settings_closed(self):
        self._settings_open = False
        self._update_hints()


# ----------------------------------------------------------------------------
# Finestra impostazioni
# ----------------------------------------------------------------------------
class SettingsWindow(tk.Toplevel):
    # stato della sezione "Aggiornamenti" (creato in __init__, usato dai metodi)
    btn_check: tk.Button
    btn_update: tk.Button
    btn_restart: tk.Button
    upd_lbl: tk.Label
    _upd_queue: queue.Queue
    _release: dict | None
    _upd_busy: bool

    def __init__(self, app: SpotlightApp, on_close):
        super().__init__(app.root)
        self.app = app
        self.on_close = on_close
        self.cfg = {**app.cfg}
        self.cfg["paths"] = list(app.cfg.get("paths", []))
        self.cfg["scripts"] = [dict(s) for s in app.cfg.get("scripts", [])]
        self.cfg["excludes"] = list(app.cfg.get("excludes", []))
        self.script_idx = -1

        self.title(f"SpotlightPy {VERSION} — Impostazioni")
        self.configure(bg=C["bg"])
        # sullo stesso schermo dello Spotlight, centrata nell'area di lavoro
        cx = app.root.winfo_x() + max(1, app.win_w) // 2
        cy = app.root.winfo_y() + max(1, app.win_h) // 2
        _device, (mon_left, mon_top, mon_right, mon_bottom) = monitor_at(cx, cy)
        avail_w = max(320, mon_right - mon_left)
        avail_h = max(320, mon_bottom - mon_top)
        w = min(int(680 * app.scale), avail_w - 60)
        h = min(int(760 * app.scale), avail_h - 90)
        x = mon_left + max(0, (avail_w - w) // 2)
        y = mon_top + max(0, (avail_h - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.f_small = tkfont.Font(family="Segoe UI", size=9)
        self.f_lbl = tkfont.Font(family="Segoe UI", size=9, weight="bold")

        # barra inferiore fissa: sempre visibile anche se il contenuto e' lungo
        self.bottom_bar = tk.Frame(self, bg=C["bg"])
        self.bottom_bar.pack(fill="x", side="bottom", pady=8, padx=12)
        self.status = tk.Label(self, text="", bg=C["bg"], fg=C["dim"],
                               font=self.f_small, anchor="w")
        self.status.pack(fill="x", side="bottom", padx=14)

        # corpo scrollabile (le sezioni finivano fuori dallo schermo)
        wrap = tk.Frame(self, bg=C["bg"])
        wrap.pack(side="top", fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=C["bg"], highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=C["bg"])
        self.body_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._sync_scroll)
        self.canvas.bind("<Configure>", self._sync_width)
        self.bind_all("<MouseWheel>", self._on_wheel)

        # ------- hotkey principale -------
        box1 = self._section("Hotkey principale (per aprire la finestra)")
        row = tk.Frame(box1, bg=C["bg2"])
        row.pack(fill="x", padx=8, pady=6)
        tk.Label(row, text="Apri / chiudi:", bg=C["bg2"], fg=C["fg"],
                 font=self.f_small).pack(side="left")
        start_hk = (self.cfg.get("hotkey") or "").strip().lower()
        if start_hk == SpotlightApp.RESERVED_LOCAL:
            start_hk = ""          # riservata alla finestra, non e' globale
        self.hk_main = HotkeyEntry(row, start_hk)
        self.hk_main.pack(side="left", padx=8)
        self._button(row, "Nessuna", self._clear_main_hotkey).pack(side="left")
        tk.Label(box1, text="Clicca il campo e premi la combinazione che vuoi. "
                            "Vuoto = nessuna hotkey (apri con doppio clic su bat/exe).",
                 bg=C["bg2"], fg=C["dim"], font=self.f_small,
                 justify="left").pack(fill="x", padx=10, pady=(0, 4))

        self.var_focus = tk.BooleanVar(value=bool(self.cfg.get("hide_on_focus_loss", True)))
        self._check(box1, "Nascondi quando la finestra perde il focus",
                    self.var_focus)
        # ------- cartelle personalizzate -------
        box2 = self._section("Cartelle personalizzate (anche di rete: \\\\server\\share)")
        listwrap = tk.Frame(box2, bg=C["bg2"])
        listwrap.pack(fill="x", padx=8, pady=4)
        self.lb_paths = tk.Listbox(listwrap, height=5, bg=C["bg3"], fg=C["fg"],
                                   selectbackground=C["accent"], bd=0,
                                   highlightthickness=0, font=self.f_small,
                                   activestyle="none")
        self.lb_paths.pack(side="left", fill="both", expand=True)
        for p in self.cfg["paths"]:
            self.lb_paths.insert("end", p)

        btns = tk.Frame(listwrap, bg=C["bg2"])
        btns.pack(side="right", fill="y", padx=(6, 0))
        self._button(btns, "Aggiungi…", self._add_path).pack(fill="x", pady=1)
        self._button(btns, "Rimuovi", self._remove_path).pack(fill="x", pady=1)
        self._button(btns, "Ricostruisci indice", self._rebuild).pack(fill="x", pady=1)

        # legenda dei colori usati nei risultati
        leg = tk.Frame(box2, bg=C["bg2"])
        leg.pack(fill="x", padx=10, pady=(4, 2))
        tk.Label(leg, text="Colori nei risultati:", bg=C["bg2"], fg=C["dim"],
                 font=self.f_small).grid(row=0, column=0, columnspan=2,
                                         sticky="w", pady=(0, 2))
        legend = (
            (C["accent"], "indice di Windows Search"),
            (C["warn"], "cartelle personalizzate di rete"),
            ("#a78bfa", "cartelle escluse dall'indice di Windows (confermate)"),
            (C["dim"], "voce rimasta nell'indice di una cartella rimossa"),
        )
        for row, (color, label) in enumerate(legend, start=1):
            tk.Label(leg, text="   ", bg=color, bd=0).grid(row=row, column=0,
                                                           sticky="w")
            tk.Label(leg, text="  " + label, bg=C["bg2"], fg=C["dim"],
                     font=self.f_small).grid(row=row, column=1, sticky="w")

        self.var_index = tk.BooleanVar(value=bool(self.cfg.get("index_on_startup", True)))
        self._check(box2, "Indicizza all'avvio (risultati istantanei)", self.var_index)
        self.var_live = tk.BooleanVar(value=bool(self.cfg.get("live_scan", True)))
        self._check(box2, "Scansiona le cartelle a ogni ricerca (rotellina)", self.var_live)
        self.var_links = tk.BooleanVar(value=bool(self.cfg.get("search_links", True)))
        self._check(box2, "Mostra anche i collegamenti (.lnk, icona con ↗)",
                    self.var_links)

        # ------- esclusioni -------
        box5 = self._section("Esclusioni (cartelle ignorate dalla scansione)")
        tk.Label(box5, text="Nomi di cartella, non percorsi (es. node_modules, .git, "
                            "Temp). Confronto senza distinzione di maiuscole.",
                 bg=C["bg2"], fg=C["dim"], font=self.f_small, anchor="w",
                 justify="left").pack(fill="x", padx=10, pady=(2, 0))
        exclwrap = tk.Frame(box5, bg=C["bg2"])
        exclwrap.pack(fill="x", padx=8, pady=4)
        self.lb_excl = tk.Listbox(exclwrap, height=4, bg=C["bg3"], fg=C["fg"],
                                  selectbackground=C["accent"], bd=0,
                                  highlightthickness=0, font=self.f_small,
                                  activestyle="none")
        self.lb_excl.pack(side="left", fill="both", expand=True)
        self.lb_excl.bind("<Double-Button-1>", lambda e: self._edit_exclude())
        ebtns = tk.Frame(exclwrap, bg=C["bg2"])
        ebtns.pack(side="right", fill="y", padx=(6, 0))
        self._button(ebtns, "Aggiungi", self._add_exclude).pack(fill="x", pady=1)
        self._button(ebtns, "Modifica", self._edit_exclude).pack(fill="x", pady=1)
        self._button(ebtns, "Rimuovi", self._del_exclude).pack(fill="x", pady=1)
        self._refresh_excludes()

        # ------- windows search -------
        box3 = self._section("Indice di Windows Search")
        self.var_win = tk.BooleanVar(value=bool(self.cfg.get("win_search", True)))
        self._check(box3, "Cerca anche nell'indice di Windows", self.var_win)
        self.var_content = tk.BooleanVar(
            value=bool(self.cfg.get("win_content_search", True)))
        self._check(box3, "Cerca anche dentro il testo dei documenti (più lento, "
                         "abilita il filtro «Solo testo»)", self.var_content)
        self.var_path = tk.BooleanVar(
            value=bool(self.cfg.get("win_path_search", True)))
        self._check(box3, "Cerca anche nel percorso (cartelle che contengono il "
                         "file); spento = solo il nome dell'elemento", self.var_path)

        # ------- script -------
        box4 = self._section("Script personalizzati (percorso = argomento)")
        tk.Label(box4, text="Elenco script: selezionane uno per modificarlo, "
                            "«Nuovo» ne crea uno da compilare.",
                 bg=C["bg2"], fg=C["dim"], font=self.f_small, anchor="w",
                 justify="left").pack(fill="x", padx=10, pady=(2, 0))
        lst = tk.Frame(box4, bg=C["bg2"])
        lst.pack(fill="x", padx=8, pady=4)
        self.lb_scripts = tk.Listbox(lst, height=4, bg=C["bg3"], fg=C["fg"],
                                     selectbackground=C["accent"], bd=0,
                                     highlightthickness=0, font=self.f_small,
                                     activestyle="none")
        self.lb_scripts.pack(side="left", fill="both", expand=True)
        self.lb_scripts.bind("<<ListboxSelect>>", self._pick_script)
        sbtns = tk.Frame(lst, bg=C["bg2"])
        sbtns.pack(side="right", fill="y", padx=(6, 0))
        self._button(sbtns, "Nuovo", self._new_script).pack(fill="x", pady=1)
        self._button(sbtns, "Rimuovi", self._del_script).pack(fill="x", pady=1)

        form = tk.Frame(box4, bg=C["bg2"])
        form.pack(fill="x", padx=8, pady=(2, 8))
        tk.Label(form, text="Dettagli dello script selezionato", bg=C["bg2"],
                 fg=C["accent"], font=self.f_lbl).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(2, 4))
        tk.Label(form, text="Nome", bg=C["bg2"], fg=C["dim"],
                 font=self.f_small).grid(row=1, column=0, sticky="w")
        self.ent_name = tk.Entry(form, bg=C["bg3"], fg=C["fg"], insertbackground=C["fg"],
                                 relief="flat", font=self.f_small)
        self.ent_name.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=2)
        tk.Label(form, text="Comando", bg=C["bg2"], fg=C["dim"],
                 font=self.f_small).grid(row=2, column=0, sticky="w")
        self.ent_cmd = tk.Entry(form, bg=C["bg3"], fg=C["fg"], insertbackground=C["fg"],
                                relief="flat", font=self.f_small)
        self.ent_cmd.grid(row=2, column=1, sticky="ew", padx=(6, 0), pady=2)
        tk.Label(form, text="Hotkey", bg=C["bg2"], fg=C["dim"],
                 font=self.f_small).grid(row=3, column=0, sticky="w")
        self.hk_script = HotkeyEntry(form, "")
        self.hk_script.grid(row=3, column=1, sticky="w", padx=(6, 0), pady=2)
        tk.Label(form, text="Usa {path} nel comando per il percorso selezionato.\n"
                            "Se non lo metti, il percorso viene aggiunto in coda.",
                 bg=C["bg2"], fg=C["dim"], font=self.f_small,
                 justify="left").grid(row=4, column=0, columnspan=2,
                                      sticky="w", pady=(4, 0))
        self.var_keep_script = tk.BooleanVar(value=False)
        tk.Checkbutton(form, text="Lanciando questo script la finestra resta aperta "
                                  "in secondo piano", variable=self.var_keep_script,
                       bg=C["bg2"], fg=C["fg"], selectcolor=C["bg3"],
                       font=self.f_small, activebackground=C["bg2"],
                       activeforeground=C["fg"], anchor="w", bd=0,
                       highlightthickness=0).grid(row=5, column=0, columnspan=2,
                                                  sticky="w", pady=(4, 0))
        self._button(form, "Salva script", self._save_script).grid(
            row=6, column=1, sticky="e", pady=(6, 0))
        form.columnconfigure(1, weight=1)

        self._refresh_scripts()

        # ------- aggiornamenti -------
        box6 = self._section("Aggiornamenti")
        tk.Label(box6, text=f"Versione installata: v{VERSION} ({updater.mode_label()})",
                 bg=C["bg2"], fg=C["fg"], font=self.f_small, anchor="w").pack(
            fill="x", padx=10, pady=(6, 2))
        urow = tk.Frame(box6, bg=C["bg2"])
        urow.pack(fill="x", padx=8, pady=(2, 4))
        self.btn_check = self._button(urow, "Controlla aggiornamenti",
                                      self._check_updates)
        self.btn_check.pack(side="left")
        self.btn_update = self._button(urow, "Aggiorna", self._do_update)
        self.btn_update.pack(side="left", padx=6)
        self.btn_update.config(state="disabled")
        self.btn_restart = self._button(urow, "Riavvia", self.app.restart_app)
        self.btn_restart.pack(side="left", padx=6)
        self.btn_restart.config(state="disabled")
        self.upd_lbl = tk.Label(
            box6, text="Premi «Controlla aggiornamenti» per vedere se ci sono novità.",
            bg=C["bg2"], fg=C["dim"], font=self.f_small, anchor="w",
            justify="left", wraplength=540)
        self.upd_lbl.pack(fill="x", padx=10, pady=(0, 6))
        self._upd_busy = False
        self._release: dict | None = None
        self._upd_queue: queue.Queue = queue.Queue()

        # ------- pulsanti -------
        self._button(self.bottom_bar, "Salva", self._save).pack(side="right")
        self._button(self.bottom_bar, "Annulla", self._cancel).pack(side="right", padx=6)
        self._button(self.bottom_bar, "Esci da SpotlightPy", self._quit).pack(side="left")

        self.transient(app.root)
        self.grab_set()
        self.after(80, self._focus)

    # ---------- scroll ----------
    def _sync_scroll(self, _event=None):
        with suppress(Exception):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _sync_width(self, event):
        with suppress(Exception):
            self.canvas.itemconfigure(self.body_id, width=event.width)

    def _on_wheel(self, event):
        step = -1 * (event.delta // 120) if getattr(event, "delta", 0) else 0
        if step:
            self.canvas.yview_scroll(step, "units")

    def destroy(self):
        with suppress(Exception):
            self.unbind_all("<MouseWheel>")
        super().destroy()

    def _clear_main_hotkey(self):
        self.hk_main.set_hotkey("")
        self.status.config(text="Hotkey principale disabilitata "
                                "(ricorda di premere Salva)", fg=C["accent"])

    def _focus(self):
        with suppress(Exception):
            self.focus_force()

    # ---------- helpers ----------
    def _section(self, title):
        box = tk.LabelFrame(self.body, text=" " + title + " ", bg=C["bg2"],
                            fg=C["accent"], font=self.f_lbl, bd=0,
                            highlightthickness=1, highlightbackground=C["border"])
        box.pack(fill="x", padx=12, pady=6)
        return box

    def _check(self, parent, text, var):
        cb = tk.Checkbutton(parent, text=text, variable=var, bg=C["bg2"],
                            fg=C["fg"], selectcolor=C["bg3"], font=self.f_small,
                            activebackground=C["bg2"], activeforeground=C["fg"],
                            anchor="w", bd=0, highlightthickness=0)
        cb.pack(fill="x", padx=10, pady=(0, 2))
        return cb

    def _button(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd, bg=C["bg3"], fg=C["fg"],
                         activebackground=C["accent"], activeforeground="#fff",
                         relief="flat", bd=0, font=self.f_small, padx=8, pady=3)

    def _err(self, msg):
        self.status.config(text=msg, fg=C["err"])

    # ---------- cartelle ----------
    def _add_path(self):
        p = filedialog.askdirectory(parent=self, title="Cartella personalizzata da cercare")
        if not p:
            return
        p = os.path.normpath(p)
        if any(os.path.normpath(x).lower() == p.lower() for x in self.cfg["paths"]):
            self.status.config(text="Questa cartella e' gia' nell'elenco", fg=C["warn"])
            self.lb_paths.selection_clear(0, "end")
            return

        kind = "net" if indexscope.is_network(p) else "excl"
        if self.var_win.get() and kind == "excl":
            indexed = indexscope.folder_in_index(p)
            if indexed:
                messagebox.showerror(
                    "Cartella gia' nell'indice di Windows",
                    f"{p}\n\nQuesta cartella e' gia' coperta dall'indice di Windows "
                    "Search: aggiungerla come cartella personalizzata darebbe "
                    "risultati duplicati.\n\nPer aggiungerla devi prima disattivare "
                    "«Cerca anche nell'indice di Windows».",
                    parent=self)
                self.status.config(text="Cartella rifiutata: e' gia' nell'indice di Windows",
                                   fg=C["err"])
                return
            ok = messagebox.askokcancel(
                "Cartella esclusa dall'indice di Windows",
                f"{p}\n\nQuesta cartella NON risulta coperta dall'indice di Windows "
                "Search (esclusa dalle opzioni di indicizzazione o fuori dagli "
                "scope).\n\nVerra' cercata solo dalla scansione dell'app e mostrata "
                "col colore delle cartelle escluse dall'indice.\n\nContinuare?",
                parent=self)
            if not ok:
                self.status.config(text="Aggiunta annullata", fg=C["warn"])
                return

        self.cfg["paths"].append(p)
        kinds = dict(self.cfg.get("path_kinds") or {})
        kinds[p.lower()] = kind
        self.cfg["path_kinds"] = kinds
        self.lb_paths.insert("end", p)
        self.status.config(
            text=("Cartella di rete aggiunta" if kind == "net"
                  else "Cartella aggiunta (esclusa dall'indice di Windows)")
                 + " — ricorda di premere Salva", fg=C["accent"])

    def _remove_path(self):
        sel = self.lb_paths.curselection()
        if sel:
            i = sel[0]
            self.lb_paths.delete(i)
            removed = self.cfg["paths"].pop(i)
            kinds = dict(self.cfg.get("path_kinds") or {})
            kinds.pop(os.path.normpath(removed).lower(), None)
            self.cfg["path_kinds"] = kinds
            self.status.config(text="Cartella rimossa (ricorda di premere Salva)",
                               fg=C["accent"])

    def _rebuild(self):
        self.app.db.clear_all()
        self.app.start_indexer(clear_first=True)
        self.status.config(text="Indice azzerato: ricostruzione avviata", fg=C["accent"])

    # ---------- esclusioni ----------
    def _refresh_excludes(self):
        self.lb_excl.delete(0, "end")
        for e in self.cfg["excludes"]:
            self.lb_excl.insert("end", e)

    def _set_exclude(self, value: str, index: int | None = None) -> bool:
        """Aggiunge (index=None) o modifica una voce di esclusione."""
        val = (value or "").strip().strip("\\/")
        if not val:
            return False
        others = [e for i, e in enumerate(self.cfg["excludes"]) if i != index]
        if any(o.lower() == val.lower() for o in others):
            self.status.config(text=f"'{val}' e' gia' presente", fg=C["warn"])
            return False
        if index is None or index >= len(self.cfg["excludes"]):
            self.cfg["excludes"].append(val)
            index = len(self.cfg["excludes"]) - 1
        else:
            self.cfg["excludes"][index] = val
        self._refresh_excludes()
        self.lb_excl.selection_clear(0, "end")
        self.lb_excl.selection_set(index)
        self.status.config(text="Esclusioni modificate (ricorda di premere Salva)",
                           fg=C["accent"])
        return True

    def _add_exclude(self):
        val = simpledialog.askstring(
            "Esclusione", "Nome della cartella da ignorare\n(es. node_modules):",
            parent=self)
        self._set_exclude(val or "")

    def _edit_exclude(self):
        sel = self.lb_excl.curselection()
        if not sel:
            self.status.config(text="Seleziona prima una voce dall'elenco", fg=C["warn"])
            return
        i = sel[0]
        val = simpledialog.askstring(
            "Esclusione", "Modifica il nome della cartella:",
            initialvalue=self.cfg["excludes"][i], parent=self)
        if val:
            self._set_exclude(val, index=i)

    def _del_exclude(self):
        sel = self.lb_excl.curselection()
        if not sel:
            self.status.config(text="Seleziona prima una voce dall'elenco", fg=C["warn"])
            return
        self.cfg["excludes"].pop(sel[0])
        self._refresh_excludes()
        self.status.config(text="Esclusione rimossa (ricorda di premere Salva)",
                           fg=C["accent"])

    # ---------- script ----------
    def _refresh_scripts(self):
        self.lb_scripts.delete(0, "end")
        for s in self.cfg["scripts"]:
            hk = (s.get("hotkey") or "").upper()
            name = s.get("name") or ("+ nuovo (da compilare)"
                                     if not s.get("command") else "script")
            mark = "  · dietro" if s.get("keep_open") else ""
            self.lb_scripts.insert("end", f"{name}  [{hk}]{mark}")

    def _pick_script(self, _ev=None):
        sel = self.lb_scripts.curselection()
        if not sel:
            return
        self.script_idx = sel[0]
        s = self.cfg["scripts"][self.script_idx]
        self.ent_name.delete(0, "end")
        self.ent_name.insert(0, s.get("name", ""))
        self.ent_cmd.delete(0, "end")
        self.ent_cmd.insert(0, s.get("command", ""))
        self.hk_script.set_hotkey(s.get("hotkey", ""))
        self.var_keep_script.set(bool(s.get("keep_open")))

    def _new_script(self):
        log("impostazioni: premuto Nuovo script")
        self.cfg["scripts"].append({"name": "", "command": "", "hotkey": ""})
        self.script_idx = len(self.cfg["scripts"]) - 1
        self._refresh_scripts()
        self.lb_scripts.selection_clear(0, "end")
        self.lb_scripts.selection_set(self.script_idx)
        self.lb_scripts.see(self.script_idx)
        self.ent_name.delete(0, "end")
        self.ent_cmd.delete(0, "end")
        self.hk_script.set_hotkey("")
        with suppress(Exception):
            self.var_keep_script.set(False)
        with suppress(Exception):
            self.ent_name.focus_set()
        self.status.config(
            text="Nuovo script: compila Nome e Comando (es. notepad {path}), "
                 "poi premi «Salva script»", fg=C["accent"])

    def _del_script(self):
        sel = self.lb_scripts.curselection()
        if not sel:
            self._err("Seleziona prima uno script dall'elenco")
            return
        i = sel[0]
        self.cfg["scripts"].pop(i)
        self.script_idx = -1
        self._refresh_scripts()
        self.ent_name.delete(0, "end")
        self.ent_cmd.delete(0, "end")
        self.hk_script.set_hotkey("")
        self.status.config(text="Script rimosso (ricorda di premere Salva)",
                           fg=C["accent"])

    def _save_script(self):
        name = self.ent_name.get().strip()
        cmd = self.ent_cmd.get().strip()
        hk = self.hk_script.get_hotkey()
        log(f"impostazioni: Salva script nome={name!r} cmd={cmd!r} hotkey={hk!r}")
        if not cmd:
            self._err("Il comando dello script e' vuoto: scrivilo nel campo Comando")
            with suppress(Exception):
                self.ent_cmd.focus_set()
            return
        entry = {"name": name or "script", "command": cmd, "hotkey": hk,
                 "keep_open": bool(self.var_keep_script.get())}
        if self.script_idx >= 0 and self.script_idx < len(self.cfg["scripts"]):
            self.cfg["scripts"][self.script_idx] = entry
        else:
            self.cfg["scripts"].append(entry)
            self.script_idx = len(self.cfg["scripts"]) - 1
        self._refresh_scripts()
        self.lb_scripts.selection_clear(0, "end")
        self.lb_scripts.selection_set(self.script_idx)
        self.status.config(text="Script salvato (ricorda di premere Salva)",
                           fg=C["accent"])

    # ---------- aggiornamenti ----------
    def _upd_start(self, kind: str, func, *args):
        if self._upd_busy:
            return
        self._upd_busy = True
        self.btn_check.config(state="disabled")
        self.btn_update.config(state="disabled")
        self.upd_lbl.config(text="Operazione in corso…", fg=C["accent"])

        def work():
            try:
                self._upd_queue.put((kind, func(*args)))
            except Exception as exc:  # noqa: BLE001 - l'errore va mostrato in GUI
                self._upd_queue.put(("error", f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=work, daemon=True, name="fe-update").start()
        self.after(150, self._upd_poll)

    def _upd_poll(self):
        try:
            kind, data = self._upd_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._upd_poll)
            return
        self._upd_busy = False
        self.btn_check.config(state="normal")
        if kind == "error":
            self.upd_lbl.config(text=f"Errore: {data}", fg=C["err"])
            return
        if kind == "check":
            self._release = data if isinstance(data, dict) else None
            tag = (self._release or {}).get("tag") or ""
            if tag and updater.is_newer(tag, VERSION):
                self.btn_update.config(state="normal")
                self.upd_lbl.config(
                    text=f"Disponibile {tag} (installata v{VERSION}). Premi «Aggiorna».",
                    fg=C["accent"])
            else:
                self.upd_lbl.config(
                    text=f"Sei aggiornato: v{VERSION} (ultima release: {tag or 'n/d'}).",
                    fg="#5fbf7f")
            return
        ok, msg = data if isinstance(data, tuple) else (False, str(data))
        self.upd_lbl.config(text=("Fatto: " if ok else "Errore: ") + msg,
                            fg="#5fbf7f" if ok else C["err"])
        if ok:
            self.btn_restart.config(state="normal")

    def _check_updates(self):
        self._upd_start("check", updater.latest_release)

    def _do_update(self):
        if not self._release:
            self.upd_lbl.config(text="Prima premi «Controlla aggiornamenti».",
                                fg=C["warn"])
            return
        if updater.is_frozen():
            self._upd_start("update", updater.update_exe, self._release.get("zip", ""))
        else:
            self._upd_start("update", updater.update_from_git, APP_DIR)

    # ---------- salva / annulla ----------
    def _save(self):
        hk = self.hk_main.get_hotkey()
        try:
            if hk:
                normalize_hotkey(hk)
        except ValueError as exc:
            self._err(f"Hotkey principale non valida: {exc}")
            return
        if hk.strip().lower() == SpotlightApp.RESERVED_LOCAL:
            self._err("Ctrl+Shift+E e' riservato alla finestra (apre la cartella "
                      "contenitrice): scegli un'altra combinazione per aprire SpotlightPy")
            return
        for s in self.cfg["scripts"]:
            if s.get("hotkey"):
                try:
                    normalize_hotkey(s["hotkey"])
                except ValueError as exc:
                    self._err(f"Hotkey dello script '{s.get('name')}' non valida: {exc}")
                    return
        # raccogli lo script eventualmente in editing
        if self.ent_cmd.get().strip():
            self._save_script()

        old_paths = list(self.app.cfg.get("paths", []))
        old_excludes = list(self.app.cfg.get("excludes", []))
        new = dict(self.app.cfg)
        new["hotkey"] = hk
        new["paths"] = list(self.cfg["paths"])
        new["scripts"] = [s for s in self.cfg["scripts"] if s.get("command")]
        new["hide_on_focus_loss"] = bool(self.var_focus.get())
        new["index_on_startup"] = bool(self.var_index.get())
        new["live_scan"] = bool(self.var_live.get())
        new["win_search"] = bool(self.var_win.get())
        new["win_content_search"] = bool(self.var_content.get())
        new["win_path_search"] = bool(self.var_path.get())
        new["excludes"] = [e for e in self.cfg["excludes"] if e]
        new["search_links"] = bool(self.var_links.get())
        kinds = {}
        for path in new["paths"]:
            key = os.path.normpath(path).lower()
            kind = (self.app.root_kinds or {}).get(key)
            if kind not in ("net", "excl"):
                kind = "net" if indexscope.is_network(path) else "excl"
            kinds[key] = kind
        new["path_kinds"] = kinds
        save_config(new)
        self.app.cfg = load_config()
        self.app._rebuild_root_kinds()
        self.app._sync_winsearch_flags()
        self.app.refresh_filter()

        self.grab_release()
        self.destroy()
        self.on_close()
        self.app._apply_hotkeys()
        if (new["paths"] != old_paths or new["excludes"] != old_excludes) \
                and new["index_on_startup"]:
            self.app.start_indexer()
        self.app.show()

    def _cancel(self):
        with suppress(Exception):
            self.grab_release()
        self.destroy()
        self.on_close()

    def _quit(self):
        """Chiude del tutto SpotlightPy (utile se la finestra non si trova piu')."""
        with suppress(Exception):
            self.grab_release()
        self.destroy()
        self.on_close()
        self.app.quit_app()


# ----------------------------------------------------------------------------
# entrypoint
# ----------------------------------------------------------------------------
_SHOW_EVENT = f"Local\\{APP_NAME}_show"
_EVENT_MODIFY_STATE = 0x0002


def _kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    return k


def _instance_role() -> str:
    """'first' se siamo l'unica istanza, 'secondary' se ce n'e' gia' una attiva."""
    try:
        k = _kernel32()
        k.CreateMutexW.restype = ctypes.c_void_p
        k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        k.CreateMutexW(None, False, f"Local\\{APP_NAME}_singleton")
        return "secondary" if ctypes.get_last_error() == 183 else "first"
    except Exception:  # noqa: BLE001 - se il check fallisce, lascia partire
        return "first"


def _signal_show() -> bool:
    """Chiede all'istanza gia' attiva di mostrare la finestra."""
    try:
        k = _kernel32()
        k.OpenEventW.restype = ctypes.c_void_p
        k.OpenEventW.argtypes = [ctypes.c_uint, ctypes.c_bool, ctypes.c_wchar_p]
        handle = k.OpenEventW(_EVENT_MODIFY_STATE, False, _SHOW_EVENT)
        if not handle:
            return False
        k.SetEvent.argtypes = [ctypes.c_void_p]
        ok = bool(k.SetEvent(handle))
        k.CloseHandle(ctypes.c_void_p(handle))
        return ok
    except Exception:  # noqa: BLE001 - se fallisce, l'altra istanza resta com'e'
        return False


def _create_show_event():
    try:
        k = _kernel32()
        k.CreateEventW.restype = ctypes.c_void_p
        k.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool,
                                   ctypes.c_wchar_p]
        return k.CreateEventW(None, False, False, _SHOW_EVENT)
    except Exception:  # noqa: BLE001
        return None


def main():
    smoke = "--smoke" in sys.argv

    def _hook(exc_type, exc, tb):
        log("ECCEZIONE NON GESTITA:\n" + "".join(
            traceback.format_exception(exc_type, exc, tb)))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook
    threading.excepthook = lambda a: log(
        "ECCEZIONE IN THREAD:\n" + "".join(
            traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))
    log(f"avvio (v{VERSION}, pid={os.getpid()}, smoke={smoke})")

    # autocontrollo della sola ricerca nell'indice di Windows (utile anche
    # dentro l'exe compilato, per verificare che pywin32 sia stato incluso)
    if "--selftest-wsearch" in sys.argv:
        from winsearch import WindowsSearch

        items, info = WindowsSearch().search("contratto", 3)
        log(f"selftest winsearch: {len(items)} risultati | {info}")
        print(f"selftest winsearch: {len(items)} risultati | {info}")
        return
    with suppress(Exception):
        ctypes.windll.shcore.SetProcessDpiAwareness(1)

    updater.cleanup_old_exe()

    show_event = None
    if not smoke:
        role = _instance_role()
        log(f"ruolo istanza: {role}")
        if role == "secondary":
            if _signal_show():
                log("altra istanza attiva: le ho chiesto di mostrare la finestra")
            else:
                log("altra istanza attiva ma segnale non recapitato")
            return
        show_event = _create_show_event()

    root = tk.Tk()
    root.title(APP_NAME)
    app = SpotlightApp(root)
    if show_event:
        app._start_show_watcher(show_event)

    startup = "--startup" in sys.argv
    if smoke:
        app.show()
        root.after(1200, root.destroy)
    elif startup:
        # avvio automatico all'accensione: la finestra NON si apre mai da sola.
        # Si apre con la hotkey globale oppure rilanciando l'app (doppio clic).
        log("avvio automatico: finestra nascosta (hotkey o doppio clic per aprirla)")
    else:
        app.show()

    try:
        root.mainloop()
    finally:
        with suppress(Exception):
            app.hotkeys.stop()
        if app.scan is not None:
            app.scan.stop_event.set()


if __name__ == "__main__":
    main()
