"""Configurazione persistente di SpotlightPy (JSON in %APPDATA%)."""

from __future__ import annotations

import copy
import json
import os

APP_NAME = "SpotlightPy"


def app_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


CONFIG_PATH = os.path.join(app_dir(), "config.json")
DB_PATH = os.path.join(app_dir(), "index.db")

DEFAULT_CONFIG = {
    # hotkey che apre/chiude la finestra (ctrl+alt+space: alt+space e' gia'
    # usato da PowerToys Run). ctrl+shift+e e' riservato alla finestra:
    # apre la cartella contenitrice dell'elemento selezionato.
    "hotkey": "ctrl+alt+space",
    # hotkey per chiudere davvero il processo (se la finestra si "perde")
    "quit_hotkey": "ctrl+shift+q",
    # ultima posizione della finestra [x, y] (aggiornata dal drag)
    "window_pos": None,
    # cartelle da scansionare (anche UNC: \\server\share\cartella)
    "paths": [],
    # script personalizzati: {"name", "command", "hotkey"}
    # nella command si puo' usare {path} (verra' sostituito dal percorso quotato)
    "scripts": [],
    # cartelle saltate durante la scansione
    "excludes": [
        "$RECYCLE.BIN",
        "System Volume Information",
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
    ],
    "win_search": True,          # interroga anche l'indice di Windows
    "win_search_limit": 40,
    "win_content_search": True,  # cerca anche nel testo dei documenti indicizzati
    "index_on_startup": True,    # costruisce l'indice locale all'avvio
    "live_scan": True,           # scansione "a vista" a ogni ricerca (rotellina)
    "search_links": True,        # includi i collegamenti .lnk nei risultati
    "max_results": 120,
    "hide_on_focus_loss": True,
    # filtro risultati: "all" | "files" | "dirs" (ciclo con Ctrl+T o click)
    "filter": "all",
}


def _merge(defaults, loaded):
    out = copy.deepcopy(defaults)
    if isinstance(loaded, dict):
        for k, v in loaded.items():
            if k in out and isinstance(out[k], type(v)):
                out[k] = v
            else:
                out[k] = v
    return out


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            loaded = json.load(f)
    except Exception:
        return copy.deepcopy(DEFAULT_CONFIG)
    return _merge(DEFAULT_CONFIG, loaded)


def save_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)
