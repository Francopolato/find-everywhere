"""Determina se una cartella è coperta dall'indice di Windows.

Si leggono le regole di indicizzazione (CrawlScopeManager) dal registro:
sono path *reali* (`file:///C:\\Users\\`), quindi non soffrono del problema dei
nomi localizzati che affligge le query su SYSTEMINDEX (`C:\\Utenti\\...`).

Per ogni regola si conosce se è di inclusione o di esclusione: vince la regola
più specifica (pattern più lungo), come fa Windows.
"""

from __future__ import annotations

import ctypes
import os
import re
import winreg

_BASES = (
    (winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\Microsoft\Windows Search\CrawlScopeManager\Windows\SystemIndex"),
    (winreg.HKEY_CURRENT_USER,
     r"SOFTWARE\Microsoft\Windows Search\CrawlScopeManager\Windows\SystemIndex"),
)
_GROUPS = ("DefaultRules", "WorkingSetRules", "PolicyRules")

_GUID = re.compile(r"\[[0-9a-fA-F-]{36}\]")
_cache: list[tuple[str, bool]] | None = None


def _to_pattern(url: str) -> str:
    """`file:///C:\\[guid]\\Users\\*\\AppData\\` -> `c:\\users\\*\\appdata\\`."""
    low = (url or "").strip().lower()
    if not low.startswith("file:"):
        return ""            # csc://, winrt://, mapi16:// … non sono percorsi
    raw = low[5:]
    raw = raw.replace("///", "", 1).replace("//", "", 1)
    raw = _GUID.sub("", raw)
    raw = raw.replace("/", "\\")
    raw = os.path.normpath(raw) if raw else ""
    return raw.lower()


def rules() -> list[tuple[str, bool]]:
    """Elenco (pattern, include) letto dal registro (in cache)."""
    global _cache
    if _cache is not None:
        return _cache
    out: list[tuple[str, bool]] = []
    for hive, sub in _BASES:
        for group in _GROUPS:
            path = f"{sub}\\{group}"
            try:
                key = winreg.OpenKey(hive, path)
            except OSError:
                continue
            try:
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        rule = winreg.OpenKey(key, name)
                    except OSError:
                        continue
                    try:
                        pattern = _to_pattern(str(_val(rule, "URL")))
                        include = _val(rule, "Include")
                        suppress = _val(rule, "Suppress")
                    finally:
                        rule.Close()
                    if pattern:
                        out.append((pattern, bool(include) and not bool(suppress)))
            finally:
                key.Close()
    _cache = out
    return out


def _val(key, name) -> int | str:
    """Legge un valore della regola (0 se manca)."""
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return 0


def _norm(path: str) -> str:
    p = os.path.normpath(str(path or "")).lower()
    return p if p.endswith("\\") else p + "\\"


def is_network(path: str) -> bool:
    """True per UNC (doppia barra) o per un'unità mappata su rete."""
    p = str(path or "")
    if p.startswith("\\\\"):
        return True
    try:
        drive = os.path.splitdrive(os.path.abspath(p))[0]
        if not drive:
            return False
        return int(ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")) == 4  # DRIVE_REMOTE
    except Exception:  # noqa: BLE001 - in dubbio si considera locale
        return False


def _matches(pattern: str, path: str) -> bool:
    """Confronto con `*` = un componente qualsiasi (nessun separatore)."""
    rx = "".join("[^\\\\]*" if ch == "*" else re.escape(ch) for ch in pattern)
    if not rx.endswith("\\\\"):
        rx += "\\\\"
    try:
        return re.match(rx, path) is not None
    except re.error:
        return False


def folder_in_index(path: str) -> bool | None:
    """True = cartella coperta dall'indice, False = no, None = non determinabile."""
    all_rules = rules()
    if not all_rules:
        return None
    target = _norm(path)
    best_inc = 0
    best_exc = 0
    for pattern, include in all_rules:
        if not _matches(pattern, target):
            continue
        if include:
            best_inc = max(best_inc, len(pattern))
        else:
            best_exc = max(best_exc, len(pattern))
    if not best_inc and not best_exc:
        return False
    return best_inc > best_exc
