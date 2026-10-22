"""Indice locale SQLite + walker veloce delle cartelle (anche di rete).

L'indice serve a dare risultati *istantanei* mentre la scansione "viva"
(quella con la rotellina) continua in background e aggiorna l'indice stesso.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time

DEFAULT_EXCLUDES = [
    "$RECYCLE.BIN",
    "System Volume Information",
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path       TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    name_lower TEXT NOT NULL,
    dir        TEXT NOT NULL,
    root       TEXT NOT NULL,
    mtime      REAL,
    size       INTEGER,
    seen_ts    REAL,
    is_dir     INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_files_name ON files(name_lower);
CREATE INDEX IF NOT EXISTS idx_files_root ON files(root);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class FileIndex:
    """Accesso all'indice SQLite (una connessione per thread)."""

    def __init__(self, path: str):
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._local = threading.local()
        conn = self.conn()
        conn.executescript(_SCHEMA)
        self._migrate(conn)
        conn.commit()

    def _migrate(self, conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(files)")}
        if "seen_ts" not in cols:
            conn.execute("ALTER TABLE files ADD COLUMN seen_ts REAL")
        if "is_dir" not in cols:
            conn.execute("ALTER TABLE files ADD COLUMN is_dir INTEGER DEFAULT 0")

    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    # ---------------- query ----------------
    def search(self, query: str, limit: int = 60) -> list[dict]:
        q = (query or "").strip().lower()
        if not q:
            return []
        conn = self.conn()
        like = "%" + _like_escape(q) + "%"
        rows = conn.execute(
            "SELECT path, name, dir, is_dir FROM files WHERE name_lower LIKE ? ESCAPE '\\' "
            "ORDER BY LENGTH(name) ASC LIMIT ?",
            (like, limit),
        ).fetchall()
        if len(rows) < max(3, limit // 4):
            extra = conn.execute(
                "SELECT path, name, dir, is_dir FROM files WHERE name_lower NOT LIKE ? ESCAPE '\\' "
                "AND dir LIKE ? ESCAPE '\\' ORDER BY LENGTH(name) ASC LIMIT ?",
                (like, like, max(0, limit - len(rows))),
            ).fetchall()
            rows += extra
        return [{"path": p, "name": n, "dir": d, "is_dir": bool(i)}
                for p, n, d, i in rows]

    def count(self) -> int:
        try:
            return int(self.conn().execute("SELECT COUNT(*) FROM files").fetchone()[0])
        except Exception:
            return 0

    # ---------------- scrittura ----------------
    def upsert(self, rows: list[tuple], ts: float | None = None) -> None:
        if not rows:
            return
        mark = time.time() if ts is None else ts
        conn = self.conn()
        conn.executemany(
            "INSERT OR REPLACE INTO files"
            "(path, name, name_lower, dir, root, mtime, size, is_dir, seen_ts) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [tuple(r) + (mark,) for r in rows],
        )
        conn.commit()

    def prune_root(self, root: str, ts: float) -> int:
        """Rimuove dal root le voci non viste nell'ultima scansione (file spariti)."""
        conn = self.conn()
        cur = conn.execute(
            "DELETE FROM files WHERE root = ? AND (seen_ts IS NULL OR seen_ts < ?)",
            (root, ts),
        )
        conn.commit()
        return cur.rowcount or 0

    def clear_root(self, root: str) -> None:
        conn = self.conn()
        conn.execute("DELETE FROM files WHERE root = ?", (root,))
        conn.commit()

    def clear_all(self) -> None:
        conn = self.conn()
        conn.execute("DELETE FROM files")
        conn.commit()


def walk(root: str, excludes=None, stop: threading.Event | None = None, batch_size: int = 800):
    """Genera batch di tuple (path, name, name_lower, dir, root, mtime, size, is_dir).

    Usa os.scandir (molto piu' veloce di Path.rglob). Elenca sia file sia
    cartelle, ma non scende dentro link/junction (evita loop infiniti).
    """
    excl = {e.lower() for e in (excludes or DEFAULT_EXCLUDES)}
    stack = [root]
    out: list[tuple] = []
    while stack:
        if stop is not None and stop.is_set():
            break
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            continue
        for e in entries:
            name = e.name
            try:
                is_link = e.is_symlink()
                is_dir = e.is_dir()          # segue i link solo per capire il tipo
                st = e.stat()
                mtime, size = st.st_mtime, st.st_size
            except OSError:
                is_link, is_dir = False, False
                mtime, size = None, None
            if is_dir and name.lower() in excl:
                continue
            out.append((e.path, name, name.lower(), current, root, mtime, size,
                        1 if is_dir else 0))
            if is_dir and not is_link:
                stack.append(e.path)
            if len(out) >= batch_size:
                yield out
                out = []
    if out:
        yield out


class IndexerThread(threading.Thread):
    """Costruisce/aggiorna l'indice all'avvio (o dopo un cambio di percorsi)."""

    def __init__(self, db: FileIndex, roots, excludes, events, clear_first: bool = False):
        super().__init__(daemon=True, name="SpotlightPy-indexer")
        self.db = db
        self.roots = [r for r in roots if r]
        self.excludes = excludes
        self.events = events
        self.clear_first = clear_first
        self.stop_event = threading.Event()

    def run(self):
        total = 0
        try:
            if self.clear_first:
                self.db.clear_all()
            for root in self.roots:
                if self.stop_event.is_set():
                    break
                if not os.path.isdir(root):
                    self.events.put(("idx", f"percorso non disponibile: {root}"))
                    continue
                self.events.put(("idx", f"Indicizzazione: {root}"))
                mark = time.time()
                n = 0
                for batch in walk(root, self.excludes, self.stop_event):
                    self.db.upsert(batch, mark)
                    n += len(batch)
                    total += len(batch)
                    if n % 2000 < len(batch):
                        self.events.put(("idx", f"Indicizzazione: {root} — {n} file"))
                if not self.stop_event.is_set():
                    removed = self.db.prune_root(root, mark)
                    if removed:
                        self.events.put(("idx", f"Rimossi {removed} riferimenti obsoleti"))
            self.events.put(("idx_done", total))
        except Exception as exc:  # pragma: no cover
            self.events.put(("idx_error", f"{type(exc).__name__}: {exc}"))


class LiveScanner(threading.Thread):
    """Scansione a ogni ricerca: streamma i risultati trovati nella cartella
    di rete/marcata (non indicizzata da Windows) e riempie l'indice."""

    def __init__(self, db: FileIndex, roots, excludes, query, events, scan_id,
                 limit: int = 200):
        super().__init__(daemon=True, name=f"SpotlightPy-scan-{scan_id}")
        self.db = db
        self.roots = [r for r in roots if r]
        self.excludes = excludes
        self.query = query
        self.ql = query.lower()
        self.events = events
        self.scan_id = scan_id
        self.limit = limit
        self.stop_event = threading.Event()

    def run(self):
        indexed = 0
        hits: list[dict] = []
        found = 0
        try:
            for root in self.roots:
                if self.stop_event.is_set():
                    return
                self.events.put(("scan_status", self.scan_id,
                                 f"Caricamento file non indicizzati in corso…  {root}"))
                for batch in walk(root, self.excludes, self.stop_event):
                    if self.stop_event.is_set():
                        return
                    self.db.upsert(batch)
                    indexed += len(batch)
                    for row in batch:
                        if self.ql in row[2] and found < self.limit:
                            hits.append({"path": row[0], "name": row[1],
                                         "dir": row[3], "is_dir": bool(row[7])})
                            found += 1
                    if hits:
                        self.events.put(("scan_hits", self.scan_id, hits))
                        hits = []
            self.events.put(("scan_done", self.scan_id, indexed))
        except Exception as exc:  # pragma: no cover
            self.events.put(("scan_error", self.scan_id, f"{type(exc).__name__}: {exc}"))
