"""Controllo e applicazione degli aggiornamenti.

Due strade, in base a come gira l'app:
  * **da sorgente** (python app.py / run.bat / FindEverywhere.pyw): `git pull --ff-only`
    nella cartella del progetto;
  * **da eseguibile** (PyInstaller): scarica lo zip dell'ultima release GitHub,
    estrae l'exe, rinomina quello in uso (`*.old`) e mette il nuovo al suo posto.
    Il riavvio è necessario (l'exe in esecuzione resta bloccato).

Nessuna dipendenza esterna: urllib, zipfile, subprocess.
Per sicurezza vengono aperte solo URL http/https.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

REPO = "Francopolato/find-everywhere"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
API_TAGS = f"https://api.github.com/repos/{REPO}/tags?per_page=100"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
TIMEOUT = 30

_ALLOWED_PREFIXES = ("https://", "http://")


def _safe_url(url: str) -> str:
    """Ammesso solo http/https (niente file:, ftp:, custom scheme…)."""
    text = str(url or "").strip()
    if not text.lower().startswith(_ALLOWED_PREFIXES):
        raise ValueError(f"URL non consentito: {text[:60]!r}")
    return text


def _open(url: str, headers: dict | None = None):
    """urlopen con schema validato: accetta solo http/https."""
    req = urllib.request.Request(_safe_url(url), headers=headers or {})  # noqa: S310
    return urllib.request.urlopen(req, timeout=TIMEOUT)  # noqa: S310


def is_frozen() -> bool:
    """True se stiamo girando dall'exe compilato."""
    return bool(getattr(sys, "frozen", False))


def mode_label() -> str:
    return "eseguibile" if is_frozen() else "sorgente"


def parse_version(text: str) -> tuple[int, ...]:
    nums: list[int] = []
    for part in str(text or "").lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        try:
            nums.append(int(digits) if digits else 0)
        except ValueError:
            nums.append(0)
    return tuple(nums) or (0,)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def latest_release() -> dict:
    """Dati dell'ultima release: {tag, zip, html, assets, tag_max, tag_max_name}.

    `tag` è l'ultima **release** pubblicata (l'unica con lo zip scaricabile);
    `tag_max` è il tag più alto esistente, che può essere più recente della
    release (tag creato ma release non ancora pubblicata).
    """
    try:
        with _open(API_LATEST, {"User-Agent": "find-everywhere-updater",
                                "Accept": "application/vnd.github+json"}) as resp:
            raw = resp.read()
    except Exception as exc:  # noqa: BLE001 - rete/API possono fallire in mille modi
        raise RuntimeError(f"impossibile contattare GitHub: {exc}") from exc

    try:
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - risposta non JSON (rate limit, proxy…)
        raise RuntimeError(f"risposta non valida da GitHub: {exc}") from exc

    assets = data.get("assets") or []
    zip_url = ""
    for asset in assets:
        if str(asset.get("name", "")).lower().endswith(".zip"):
            zip_url = asset.get("browser_download_url") or ""
            break

    tag_max_name, tag_max = _highest_tag()
    return {
        "tag": data.get("tag_name") or "",
        "zip": zip_url,
        "html": data.get("html_url") or RELEASES_PAGE,
        "assets": [a.get("name") for a in assets],
        "tag_max": tag_max,
        "tag_max_name": tag_max_name,
    }


def _highest_tag() -> tuple[str, str]:
    """(nome, versione) del tag più alto, es. ('v1.32', '1.32')."""
    try:
        with _open(API_TAGS, {"User-Agent": "find-everywhere-updater",
                              "Accept": "application/vnd.github+json"}) as resp:
            raw = resp.read()
        tags = json.loads(raw)
    except Exception:  # noqa: BLE001 - se i tag non si leggono si prosegue
        return "", ""
    best_name = ""
    best_ver: tuple[int, ...] = (0,)
    if isinstance(tags, list):
        for item in tags:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            ver = parse_version(name)
            if ver > best_ver:
                best_ver, best_name = ver, name
    return best_name, (best_name[1:] if best_name[:1] in ("v", "V") else best_name)


def update_from_git(app_dir: str) -> tuple[bool, str]:
    """Aggiorna un'installazione da sorgente con `git pull --ff-only`."""
    try:
        res = subprocess.run(
            ["git", "-C", app_dir, "pull", "--ff-only"],
            capture_output=True, text=True, timeout=180,
        )
    except FileNotFoundError:
        return False, "git non trovato nel PATH"
    except subprocess.TimeoutExpired:
        return False, "git pull: tempo scaduto"
    out = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
    if res.returncode == 0:
        return True, out or "già aggiornato"
    return False, out or f"git pull è uscito con codice {res.returncode}"


def _download(url: str, dest: str) -> None:
    """Scarica un file (solo http/https) in `dest`."""
    with _open(url) as src:
        try:
            with open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
        except OSError as exc:
            raise RuntimeError(f"impossibile scrivere {dest}: {exc}") from exc


def update_exe(zip_url: str) -> tuple[bool, str]:
    """Sostituisce l'exe in esecuzione con quello contenuto nello zip della release."""
    if not is_frozen():
        return False, "non sto girando da eseguibile"
    if not zip_url:
        return False, "la release non ha un pacchetto .zip da scaricare"
    exe = os.path.abspath(sys.executable)
    tmp = tempfile.mkdtemp(prefix="fe-update-")
    try:
        pkg = os.path.join(tmp, "pkg.zip")
        _download(zip_url, pkg)
        with zipfile.ZipFile(pkg) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".exe")]
            if not names:
                return False, "nessun eseguibile dentro lo zip"
            new_exe = os.path.join(tmp, "new.exe")
            with z.open(sorted(names, key=len)[0]) as src, open(new_exe, "wb") as dst:
                shutil.copyfileobj(src, dst)
        old = exe + ".old"
        try:
            if os.path.exists(old):
                os.remove(old)
        except OSError:
            pass
        os.rename(exe, old)              # possibile anche con l'exe in esecuzione
        try:
            os.replace(new_exe, exe)
        except Exception:
            os.rename(old, exe)          # ripristina in caso di problemi
            raise
        return True, "eseguibile sostituito: riavvia per usare la nuova versione"
    except Exception as exc:  # noqa: BLE001 - va mostrato all'utente
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cleanup_old_exe() -> None:
    """Rimuove il `*.old` lasciato dall'aggiornamento precedente."""
    if not is_frozen():
        return
    stale = os.path.abspath(sys.executable) + ".old"
    try:
        if os.path.exists(stale):
            os.remove(stale)
    except OSError:
        return
