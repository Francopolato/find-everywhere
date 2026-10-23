"""Ricerca nell'indice di Windows (Windows Search / SYSTEMINDEX) via OLEDB.

Tre strategie in cascata, come fa PowerToys:
  1. nome visualizzato   System.ItemNameDisplay LIKE '%q%'
  2. nome file           System.FileName LIKE '%q%'
  3. contenuto           FREETEXT(System.Search.Contents, 'q')

La 3 parte solo se le prime due non bastano, cosi' il caso normale resta
rapido (~0,3 s) e la ricerca nel testo dei documenti e' comunque disponibile.

Usa pywin32 (win32com) e degrada senza far danni se non e' disponibile.
"""

from __future__ import annotations

import os
import threading
from contextlib import suppress
from urllib.parse import unquote

_PROVIDER = "Provider=Search.CollatorDSO;Extended Properties='Application=Windows';"

# Windows Search non supporta query parametrizzate su SYSTEMINDEX: la
# condizione viene costruita qui, con l'apostrofo raddoppiato (escape SQL).
_SQL_TEMPLATE = (
    "SELECT TOP @@LIMIT@@ System.ItemNameDisplay, System.ItemPathDisplay, "
    "System.ItemUrl FROM SYSTEMINDEX WHERE @@WHERE@@"
)

# (etichetta, condizione SQL; @@V@@ = valore gia' quotato correttamente)
_STRATEGIES = (
    ("nome", "System.ItemNameDisplay LIKE '@@V@@'"),
    ("file", "System.FileName LIKE '@@V@@'"),
    ("percorso", "System.ItemPathDisplay LIKE '@@V@@'"),
    ("testo", "FREETEXT(System.Search.Contents, '@@V@@')"),
)


def build_sql(limit: int, condition: str) -> str:
    sql = _SQL_TEMPLATE.replace("@@LIMIT@@", str(int(limit)))
    return sql.replace("@@WHERE@@", condition)


def path_from_url(url: str) -> str:
    """Da 'file:C:/Users/...' al percorso reale 'C:\\Users\\...'.

    Serve perche' System.ItemPathDisplay restituisce il percorso *localizzato*
    (es. C:\\Utenti\\Polat\\Documenti\\...) che su disco non esiste.
    """
    u = (url or "").strip()
    if not u:
        return ""
    low = u.lower()
    if low.startswith("file:///"):
        u = u[8:]
    elif low.startswith("file://"):
        u = "\\\\" + u[7:]
    elif low.startswith("file:"):
        u = u[5:]
    elif low.startswith(("http:", "https:", "mapi:", "outlook:")):
        return ""
    return unquote(u).replace("/", "\\")


class WindowsSearch:
    def __init__(self):
        self._lock = threading.Lock()
        self.available: bool | None = None   # None = non ancora provato
        self.last_error: str = ""
        self.last_info: dict = {}

    # ------------------------------------------------------------------
    def _connect(self):
        import pythoncom  # pywin32
        import win32com.client

        pythoncom.CoInitialize()
        conn = win32com.client.Dispatch("ADODB.Connection")
        conn.Open(_PROVIDER)
        return conn

    @staticmethod
    def _rows(conn, sql: str) -> list[tuple]:
        rs = conn.Execute(sql)[0]
        out = []
        while not rs.EOF:
            out.append((rs.Fields.Item(0).Value, rs.Fields.Item(1).Value,
                        rs.Fields.Item(2).Value))
            rs.MoveNext()
        rs.Close()
        return out

    @staticmethod
    def _keep(name, path) -> bool:
        if not path or not name:
            return False
        low = str(path).lower()
        return not ("://" in low or low.startswith(("mapi:", "outlook:")))

    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 40,
               content: bool = True) -> tuple[list[dict], dict]:
        """Ritorna (risultati, info). info raccoglie diagnosi per la UI/log."""
        q = (query or "").strip()
        info: dict = {"strategies": [], "error": None, "count": 0}
        if not q:
            self.last_info = info
            return [], info
        safe = q.replace("'", "''")

        strategies = list(_STRATEGIES)
        if not content:
            strategies = [s for s in strategies if s[0] != "testo"]

        items: list[dict] = []
        seen: set[str] = set()
        want = max(5, limit // 2)
        conn = None
        try:
            with self._lock:
                conn = self._connect()
                for label, cond in strategies:
                    if label != "nome" and len(items) >= want:
                        break
                    value = safe if label == "testo" else f"%{safe}%"
                    sql = build_sql(limit, cond.replace("@@V@@", value))
                    rows = self._rows(conn, sql)
                    info["strategies"].append(f"{label}:{len(rows)}")
                    for name, shown_path, url in rows:
                        if not self._keep(name, shown_path or url):
                            continue
                        real = path_from_url(url)
                        path = real or str(shown_path or "")
                        low = path.lower()
                        if not path or low in seen:
                            continue
                        seen.add(low)
                        # Windows Search non dice se l'elemento e' una cartella:
                        # lo verifica direttamente sul filesystem (i percorsi
                        # dell'indice sono locali e verificati).
                        items.append({
                            "path": path,
                            "name": str(name),
                            "dir": path.rsplit("\\", 1)[0],
                            "source": "pc",
                            "match": label,
                            "is_dir": os.path.isdir(path),
                        })
                        if len(items) >= limit:
                            break
                    if len(items) >= limit:
                        break
            self.available = True
        except Exception as exc:  # noqa: BLE001 - Windows Search puo' non esserci
            self.available = False
            self.last_error = f"{type(exc).__name__}: {exc}"
            info["error"] = self.last_error
        finally:
            if conn is not None:
                with suppress(Exception):
                    conn.Close()
                with suppress(Exception):
                    import pythoncom

                    pythoncom.CoUninitialize()

        info["count"] = len(items)
        self.last_info = info
        return items, info
