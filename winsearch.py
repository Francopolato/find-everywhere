"""Ricerca nell'indice di Windows (Windows Search / SYSTEMINDEX) via OLEDB.

Strategie (tutte basate sull'indice full-text, quindi veloci):
  1. `nome`     CONTAINS(System.FileName, '"term1*" AND "term2*" ...')
  2. `percorso` CONTAINS(System.ItemPathDisplay, ...)  -> la cartella che contiene i termini
  3. `testo`    FREETEXT(System.Search.Contents, ...)  -> contenuto dei documenti

Note importanti:
* ogni termine e' cercato come **prefisso di parola** (`term*`), che e' cio'
  che l'indice sa fare in fretta; la ricerca di sottostringa con
  `LIKE '%term%'` costava 12+ secondi per query, quindi non si usa piu';
* i `*` digitati dell'utente hanno lo stesso effetto (separano i termini);
* i termini possono comparire in qualunque ordine.
"""

from __future__ import annotations

import os
import threading
from contextlib import suppress
from urllib.parse import unquote

from query import like_pattern, search_terms
from query import terms as query_terms

_PROVIDER = "Provider=Search.CollatorDSO;Extended Properties='Application=Windows';"

_SQL_TEMPLATE = (
    "SELECT TOP @@LIMIT@@ System.ItemNameDisplay, System.ItemPathDisplay, "
    "System.ItemUrl FROM SYSTEMINDEX WHERE @@WHERE@@"
)


def build_sql(limit: int, condition: str) -> str:
    sql = _SQL_TEMPLATE.replace("@@LIMIT@@", str(int(limit)))
    return sql.replace("@@WHERE@@", condition)


def contains_condition(prop: str, terms: list[str]) -> str:
    """`CONTAINS(prop, '"a*" AND "b*"')` — prefissi di parola, tutti obbligatori."""
    safe_terms = [t.replace("'", "''").replace('"', "") for t in terms]
    expr = " AND ".join(f'"{t}*"' for t in safe_terms)
    return f"CONTAINS({prop}, '{expr}')"


def freetext_condition(text: str) -> str:
    return f"FREETEXT(System.Search.Contents, '{text}')"


def contains_like(prop: str, query: str) -> str:
    """`prop LIKE '%testo%'` (Windows Search non supporta ESCAPE)."""
    pattern = like_pattern(query, escape=False).replace("'", "''")
    return f"{prop} LIKE '{pattern}'"


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
        terms = query_terms(q)
        if not terms:
            self.last_info = info
            return [], info

        strategies = []
        if len(terms) == 1:
            # un solo termine: LIKE con % ai lati = ricerca anche a meta' parola
            # (`*tratt` trova "contratto"). Misurato ~0,3 s, accettabile.
            strategies.append(("nome", contains_like("System.ItemNameDisplay", q)))
        else:
            # piu' termini: CONTAINS con prefissi di parola. Il LIKE multi-termine
            # (`%a%b%`) costa 12+ secondi, quindi non si usa.
            strategies.append(("nome", contains_condition("System.FileName", terms)))
        strategies.append(("percorso", contains_condition("System.ItemPathDisplay", terms)))
        if content:
            strategies.append(("testo", freetext_condition(search_terms(q))))

        items: list[dict] = []
        seen: set[str] = set()
        want = max(5, limit // 2)
        conn = None
        try:
            with self._lock:
                conn = self._connect()
                for label, where in strategies:
                    if label != "nome" and len(items) >= want:
                        break
                    rows = self._rows(conn, build_sql(limit, where))
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
                        # lo verifica direttamente sul filesystem.
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
