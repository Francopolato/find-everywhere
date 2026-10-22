"""Hotkey globali di sistema con ctypes (RegisterHotKey + message loop).

Nessuna dipendenza esterna. Ogni hotkey e' una stringa tipo "ctrl+shift+e".
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import queue
import threading

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

_MOD_NAMES = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "alt": MOD_ALT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "windows": MOD_WIN,
}

_SPECIAL = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09, "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D,
    "ins": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "prior": 0x21, "next": 0x22, "up": 0x26, "down": 0x28, "left": 0x25,
    "right": 0x27, "comma": 0xBC, "period": 0xBE, "slash": 0xBF,
    "semicolon": 0xBA, "quote": 0xDE, "bracketleft": 0xDB,
    "bracketright": 0xDD, "backslash": 0xDC, "minus": 0xBD, "equal": 0xBB,
    "grave": 0xC0, "+": 0xBB, "-": 0xBD, ",": 0xBC, ".": 0xBE, "/": 0xBF,
}

# tasti "sporchi" generati dal layout italiano/europeo
_EXTRA = {
    "plus": 0xBB, "asterisk": 0x6A, "numbersign": 0xBF, "egrave": 0xE8,
    "agrave": 0xE0, "ograve": 0xF2, "ugrave": 0xF9, "igrave": 0xEC,
}

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def normalize_hotkey(spec: str) -> str:
    """'Ctrl + Shift + E' -> 'ctrl+shift+e'. Solleva ValueError se non valida."""
    parse_hotkey(spec)
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    order = ["ctrl", "shift", "alt", "win"]
    mods = list(parts[:-1])
    key = parts[-1]
    mods_sorted = [m for m in order if m in mods]
    return "+".join(mods_sorted + [key])


def parse_hotkey(spec: str) -> tuple[int, int]:
    if not spec or not spec.strip():
        raise ValueError("combinazione vuota")
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ValueError("combinazione vuota")
    key = parts[-1]
    mods = 0
    for m in parts[:-1]:
        if m not in _MOD_NAMES:
            raise ValueError(f"modificatore sconosciuto: {m}")
        mods |= _MOD_NAMES[m]
    # tasto
    if len(key) == 1 and (key.isalnum() or key in ".,-/;'[]\\=`+"):
        vk = _SPECIAL.get(key)
        if vk is None:
            vk = ord(key.upper())
    elif key in _SPECIAL:
        vk = _SPECIAL[key]
    elif key in _EXTRA:
        vk = _EXTRA[key]
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError(f"tasto sconosciuto: {key}")
    if mods == 0:
        # un singolo tasto nudo bloccherebbe la digitazione: vietato
        raise ValueError("serve almeno un modificatore (ctrl/alt/shift/win)")
    return mods, vk


class HotkeyManager:
    """Registra hotkey globali e consegna gli eventi tramite una coda."""

    def __init__(self):
        self.events: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self.errors: list[str] = []

    def start(self, bindings: dict[str, str]) -> list[str]:
        """bindings: nome -> stringa hotkey. Ritorna la lista di errori."""
        self.stop()
        self.errors = []
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run, args=(dict(bindings),), daemon=True,
            name="SpotlightPy-hotkeys")
        self._thread.start()
        self._ready.wait(timeout=5)
        return list(self.errors)

    def stop(self):
        if self._thread is not None and self._thread.is_alive() and self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(timeout=1.5)
        self._thread = None
        self._thread_id = None

    def alive(self) -> bool:
        """True se il thread del message loop (e quindi le hotkey) e' attivo."""
        return bool(self._thread is not None and self._thread.is_alive())

    # ------------------------------------------------------------------
    def _run(self, bindings: dict[str, str]):
        self._thread_id = kernel32.GetCurrentThreadId()
        registered: list[tuple[int, str]] = []
        hid = 1
        for name, spec in bindings.items():
            if not spec:
                continue
            try:
                mods, vk = parse_hotkey(spec)
            except ValueError as exc:
                self.errors.append(f"{name}: {exc}")
                continue
            key = hid
            if not user32.RegisterHotKey(None, key, mods | MOD_NOREPEAT, vk):
                err = ctypes.get_last_error()
                self.errors.append(
                    f"{name} ({spec}): non registrata (codice {err}) — "
                    "forse e' gia' usata da un altro programma")
            else:
                registered.append((key, name))
            hid += 1
        names = dict(registered)
        self._ready.set()

        msg = wt.MSG()
        try:
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0 or ret == -1:
                    break
                if msg.message == WM_HOTKEY:
                    name = names.get(int(msg.wParam))
                    if name:
                        self.events.put(name)
        finally:
            for key, _ in registered:
                user32.UnregisterHotKey(None, key)
