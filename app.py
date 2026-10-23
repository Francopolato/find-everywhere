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
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from contextlib import suppress
from tkinter import filedialog, ttk
from tkinter import font as tkfont

from config import APP_NAME, DB_PATH, app_dir, load_config, save_config
from hotkeys import HotkeyManager, normalize_hotkey
from indexer import FileIndex, IndexerThread, LiveScanner
from winsearch import WindowsSearch

LOG_PATH = os.path.join(app_dir(), "spotlightpy.log")
VERSION = "1.7"


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
        self.status_text = ""
        self.status_kind = "dim"
        self._spin = 0
        self._debounce = None
        self._settings_open = False
        self._tmp_indexer = None
        self._quitting = False
        self._tick_count = 0
        self.win_info: dict = {}

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
        self.font_icon = tkfont.Font(family="Segoe UI Emoji", size=12)

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
        with suppress(Exception):
            save_config(self.cfg)

    def _update_hints(self):
        parts = ["Invio / click: apri", "Ctrl+Shift+E: cartella contenitrice",
                 "↑↓: naviga", "Esc: chiudi", "Ctrl+,: impostazioni"]
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
    def show(self):
        self._shown_at = time.time()
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
        if not self.results:
            self._render()

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
        if self._settings_open:
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
        self._debounce = self.root.after(130, self._run_search)

    def _run_search(self):
        self._debounce = None
        q = self.entry.get().strip()
        self.query_now = q
        self._stop_scan()
        self.sel = 0
        self.offset = 0
        self.results = []
        self.seen = set()

        if not q:
            self.busy_scan = False
            self.set_status("")
            self._render()
            return

        # 1) risultati istantanei dall'indice locale (gia' scansionato)
        self._merge(self.db.search(q, limit=self.cfg.get("max_results", 120)), "index")
        self._render()

        # 2) indice di Windows (thread separato, ~150-400ms)
        if self.cfg.get("win_search") and len(q) >= 2:
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

    def _win_bg(self, q):
        try:
            items, info = self.winsearch.search(
                q,
                limit=self.cfg.get("win_search_limit", 40),
                content=bool(self.cfg.get("win_content_search", True)),
            )
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

    def _merge(self, items, source):
        added = False
        for it in items:
            path = it.get("path")
            if not path:
                continue
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
            n = (it.get("name") or "").lower()
            if n == q:
                s = 0
            elif n.startswith(q):
                s = 1
            elif q in n:
                s = 2
            else:
                s = 3
            return (s, len(n), it["path"].lower())

        self.results.sort(key=score)
        maxr = self.cfg.get("max_results", 120)
        if len(self.results) > maxr:
            dropped = self.results[maxr:]
            self.results = self.results[:maxr]
            for it in dropped:
                self.seen.discard(it["path"].lower())
        if self.sel >= len(self.results):
            self.sel = max(0, len(self.results) - 1)

    # ------------------------------------------------------- rendering
    def _render(self):
        for w in self.rows_frame.winfo_children():
            w.destroy()
        self.row_widgets = []

        if not self.results:
            msg = ("Scrivi per cercare…" if not self.query_now
                   else "Nessun risultato")
            tk.Label(self.rows_frame, text=msg, bg=C["bg"], fg=C["dim"],
                     font=self.font_row).pack(pady=24)
            return

        total = len(self.results)
        self.offset = max(0, min(self.offset, max(0, total - MAX_ROWS)))
        visible = self.results[self.offset:self.offset + MAX_ROWS]

        for i, item in enumerate(visible):
            abs_idx = self.offset + i
            f = tk.Frame(self.rows_frame, bg=C["bg"], cursor="hand2")
            f.pack(fill="x", padx=8, pady=1)

            source = str(item.get("source") or "index")
            if item.get("is_dir"):
                icon = "🗂"
            elif item.get("match") == "testo":
                icon = "📃"
            else:
                icon = {"pc": "🖥", "net": "🌐", "index": "📄"}.get(source, "📄")
            lbl_i = tk.Label(f, text=icon, bg=C["bg"], fg=C["accent"],
                             font=self.font_icon, width=2)
            lbl_i.pack(side="left")

            lbl_n = tk.Label(f, text=item["name"], bg=C["bg"], fg=C["fg"],
                             font=self.font_row_b, anchor="w")
            lbl_n.pack(side="left")

            avail = max(20, int((self.win_w - 210) / (8 * self.scale / 1.4)))
            dir_text = item["dir"]
            if item.get("match") == "testo":
                dir_text = "testo · " + dir_text
            lbl_d = tk.Label(f, text=_shorten(dir_text, int(avail)),
                             bg=C["bg"], fg=C["dim"], font=self.font_row, anchor="e")
            lbl_d.pack(side="right", padx=(8, 6))

            for w in (f, lbl_i, lbl_n, lbl_d):
                w.bind("<Button-1>", lambda e, i=abs_idx: self._click_row(i))
                w.bind("<Button-3>", lambda e, i=abs_idx: self._context_menu(e, i))
                w.bind("<Enter>", lambda e, i=abs_idx: self._hover(i))
            self.row_widgets.append((abs_idx, f, lbl_i, lbl_n, lbl_d))

        self._paint_selection()

    def _paint_selection(self):
        for abs_idx, f, lbl_i, lbl_n, lbl_d in self.row_widgets:
            if abs_idx == self.sel:
                bg, fg = C["sel"], "#ffffff"
            else:
                bg, fg = C["bg"], C["fg"]
            f.config(bg=bg)
            lbl_i.config(bg=bg)
            lbl_n.config(bg=bg, fg=fg)
            lbl_d.config(bg=bg, fg="#b9c3d6" if abs_idx == self.sel else C["dim"])

    def _hover(self, idx):
        if idx != self.sel:
            self._select(idx, scroll=False)

    def _select(self, idx, scroll=True):
        if not self.results:
            return
        idx = max(0, min(idx, len(self.results) - 1))
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
        if not self.results:
            return "break"
        self._select(self.sel + delta)
        return "break"

    def _on_wheel(self, event):
        if not self.results:
            return
        up = getattr(event, "delta", 0) > 0 or getattr(event, "num", 0) == 4
        step = -1 if up else 1
        new_off = max(0, min(self.offset + step * 2,
                             max(0, len(self.results) - MAX_ROWS)))
        if new_off != self.offset:
            self.offset = new_off
            self._render()

    def _click_row(self, idx):
        self.sel = idx
        self._activate(reveal=False)

    def _selected_item(self):
        if 0 <= self.sel < len(self.results):
            return self.results[self.sel]
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
        self.hide()
        try:
            log(f"script {script.get('name')!r}: {cmdline}")
            launch(cmdline)
        except Exception as exc:  # noqa: BLE001 - qualunque errore va mostrato
            log(f"errore script: {type(exc).__name__}: {exc}")
            self.set_status(f"Errore script: {exc}", "err")

    def _context_menu(self, event, idx):
        self._select(idx)
        it = self._selected_item()
        if not it:
            return
        path = it["path"]
        m = tk.Menu(self.root, tearoff=0, bg=C["bg2"], fg=C["fg"],
                    activebackground=C["accent"], activeforeground="#fff",
                    bd=0)
        m.add_command(label="Apri", command=lambda: self._activate(False))
        m.add_command(label="Apri cartella contenitrice",
                      command=lambda: self._activate(True))
        m.add_command(label="Copia percorso", command=lambda: self._copy_path(path))
        scripts = self.cfg.get("scripts", [])
        if scripts:
            m.add_separator()
            for s in scripts:
                label = s.get("name") or "script"
                if s.get("hotkey"):
                    label += f"  [{s['hotkey'].upper()}]"
                m.add_command(label=label,
                              command=lambda sc=s: self._run_script(sc, path))
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
        busy = self.busy_scan or self.busy_index
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
            self.win_info = info
            log(f"ricerca {q!r}: windows={len(items)} "
                f"[{' '.join(info.get('strategies') or [])}] "
                f"errore={info.get('error')}")
            merged = self._merge(items, "pc")
            if merged:
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
        elif kind == "scan_error":
            if ev[1] == self.scan_id:
                self.busy_scan = False
                self.set_status(f"Errore scansione: {ev[2]}", "err")
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
    def __init__(self, app: SpotlightApp, on_close):
        super().__init__(app.root)
        self.app = app
        self.on_close = on_close
        self.cfg = {**app.cfg}
        self.cfg["paths"] = list(app.cfg.get("paths", []))
        self.cfg["scripts"] = [dict(s) for s in app.cfg.get("scripts", [])]
        self.script_idx = -1

        self.title(f"SpotlightPy {VERSION} — Impostazioni")
        self.configure(bg=C["bg"])
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = min(int(680 * app.scale), sw - 60)
        h = min(int(760 * app.scale), sh - 90)
        self.geometry(f"{w}x{h}")
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

        # ------- cartelle -------
        box2 = self._section("Cartelle da cercare (anche di rete: \\\\server\\share)")
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

        self.var_index = tk.BooleanVar(value=bool(self.cfg.get("index_on_startup", True)))
        self._check(box2, "Indicizza all'avvio (risultati istantanei)", self.var_index)
        self.var_live = tk.BooleanVar(value=bool(self.cfg.get("live_scan", True)))
        self._check(box2, "Scansiona le cartelle a ogni ricerca (rotellina)", self.var_live)

        # ------- windows search -------
        box3 = self._section("Indice di Windows Search")
        self.var_win = tk.BooleanVar(value=bool(self.cfg.get("win_search", True)))
        self._check(box3, "Cerca anche nell'indice di Windows", self.var_win)

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
        self._button(form, "Salva script", self._save_script).grid(
            row=5, column=1, sticky="e", pady=(6, 0))
        form.columnconfigure(1, weight=1)

        self._refresh_scripts()

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
        p = filedialog.askdirectory(parent=self, title="Cartella da cercare")
        if p:
            p = os.path.normpath(p)
            if p not in self.cfg["paths"]:
                self.cfg["paths"].append(p)
                self.lb_paths.insert("end", p)

    def _remove_path(self):
        sel = self.lb_paths.curselection()
        if sel:
            i = sel[0]
            self.lb_paths.delete(i)
            self.cfg["paths"].pop(i)

    def _rebuild(self):
        self.app.db.clear_all()
        self.app.start_indexer(clear_first=True)
        self.status.config(text="Indice azzerato: ricostruzione avviata", fg=C["accent"])

    # ---------- script ----------
    def _refresh_scripts(self):
        self.lb_scripts.delete(0, "end")
        for s in self.cfg["scripts"]:
            hk = (s.get("hotkey") or "").upper()
            name = s.get("name") or ("+ nuovo (da compilare)"
                                     if not s.get("command") else "script")
            self.lb_scripts.insert("end", f"{name}  [{hk}]")

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
        entry = {"name": name or "script", "command": cmd, "hotkey": hk}
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
        new = dict(self.app.cfg)
        new["hotkey"] = hk
        new["paths"] = list(self.cfg["paths"])
        new["scripts"] = [s for s in self.cfg["scripts"] if s.get("command")]
        new["hide_on_focus_loss"] = bool(self.var_focus.get())
        new["index_on_startup"] = bool(self.var_index.get())
        new["live_scan"] = bool(self.var_live.get())
        new["win_search"] = bool(self.var_win.get())
        save_config(new)
        self.app.cfg = load_config()

        self.grab_release()
        self.destroy()
        self.on_close()
        self.app._apply_hotkeys()
        if new["paths"] != old_paths and new["index_on_startup"]:
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

    if smoke:
        app.show()
        root.after(1200, root.destroy)
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
