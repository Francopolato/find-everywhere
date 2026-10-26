"""Risoluzione dei collegamenti `.lnk` (target e se il target è una cartella).

Serve per dare ai collegamenti un'icona distinta (cartella o file con la
freccia in basso a destra, come in Esplora file) e per mostrare la destinazione.
Il risultato è messo in cache: la stessa .lnk viene risolta una sola volta.
"""

from __future__ import annotations

import os
import threading

LINK_EXT = ".lnk"
MARK = "\u2197"          # freccia in alto a destra, come overlay dei .lnk

_cache: dict[str, tuple[str, bool]] = {}
_lock = threading.Lock()


def is_link(path: str) -> bool:
    return str(path).lower().endswith(LINK_EXT)


def _shell():
    import pythoncom  # pywin32
    import win32com.client

    pythoncom.CoInitialize()
    return win32com.client.Dispatch("WScript.Shell")


def _looks_like_folder(target: str) -> bool:
    """True se il target del collegamento è una cartella.

    Se il target non è raggiungibile (share di rete offline, unità scollegata)
    `isdir` fallisce: in quel caso si usa l'euristica "l'ultimo elemento non ha
    estensione", perché le cartelle di solito non ne hanno.
    """
    if not target:
        return False
    try:
        if os.path.isdir(target):
            return True
    except OSError:
        return False
    leaf = os.path.basename(str(target).rstrip("\\/"))
    return bool(leaf) and "." not in leaf


def resolve_link(path: str) -> tuple[str, bool]:
    """Ritorna (target, target_e_cartella). ("", False) se non risolvibile."""
    key = str(path).lower()
    with _lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached

    target = ""
    is_dir = False
    try:
        target = _shell().CreateShortcut(path).TargetPath or ""
        is_dir = _looks_like_folder(target)
    except Exception:  # noqa: BLE001 - collegamento rotto o non leggibile
        target, is_dir = "", False

    with _lock:
        _cache[key] = (target, is_dir)
    return target, is_dir


def describe(path: str) -> dict:
    """Informazioni per la GUI su un percorso (link o no)."""
    if not is_link(path):
        return {"is_link": False, "link_target": "", "link_is_dir": False}
    target, is_dir = resolve_link(path)
    return {"is_link": True, "link_target": target, "link_is_dir": is_dir}
