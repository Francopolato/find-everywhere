"""Interpretazione della query di ricerca, con il carattere jolly `*`.

`*` vale "uno o più caratteri qualsiasi", es:
    scafallatur*metall*ord*23440
trova i nomi che contengono "scafallatur", poi (dopo almeno un carattere)
"metall", poi "ord", poi "23440", in quest'ordine.

Senza `*` la ricerca resta la solita sottostringa.
La stessa traduzione vale per SQLite (`LIKE ... ESCAPE '\\'`) e per Windows
Search (`LIKE`), cosi' i risultati sono coerenti fra le fonti.
"""

from __future__ import annotations

import re

WILDCARD = "*"


def is_empty(query: str) -> bool:
    return not (query or "").replace(WILDCARD, "").strip()


def has_wildcard(query: str) -> bool:
    return WILDCARD in (query or "")


def parts(query: str) -> list[str]:
    return [p for p in (query or "").split(WILDCARD) if p]


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _pieces(query: str) -> list[str]:
    """Parti non vuote della query, senza il jolly iniziale/finale.

    Un `*` in testa o in coda significa "qualsiasi cosa", quindi non deve
    obbligare a un carattere in più (il `%` ai bordi lo copre già).
    """
    pieces = (query or "").split(WILDCARD)
    if pieces and pieces[0] == "":
        pieces = pieces[1:]
    if pieces and pieces[-1] == "":
        pieces = pieces[:-1]
    return [p for p in pieces if p]


def like_pattern(query: str, escape: bool = True) -> str:
    """Pattern per `LIKE`.

    Ogni `*` interno diventa `_%`: `_` = un carattere obbligatorio, `%` =
    qualsiasi sequenza, quindi "uno o piu' caratteri qualsiasi".

    `escape=True` protegge `%` e `_` scritti dall'utente (serve la clausola
    `ESCAPE '\\'`, supportata da SQLite ma **non** da Windows Search).
    """
    q = (query or "").strip()
    if is_empty(q):
        return "%"
    esc = _escape_like if escape else (lambda s: s)
    if not has_wildcard(q):
        return "%" + esc(q) + "%"
    pieces = _pieces(q)
    if not pieces:
        return "%"
    return "%" + "_%".join(esc(p) for p in pieces) + "%"


def search_terms(query: str) -> str:
    """Testo 'pulito' dai jolly, per motori che non li supportano (FREETEXT)."""
    return " ".join(terms(query)) or (query or "").strip()


def terms(query: str) -> list[str]:
    """Parole della query, senza jolly: `a*b c` -> ['a', 'b', 'c']

    Ogni `*` separa termini (equivalente a "prefisso di parola" per l'indice di
    Windows), e anche gli spazi separano.
    """
    out: list[str] = []
    for piece in (query or "").split(WILDCARD):
        for word in piece.split():
            word = word.strip('"\'()[]{}.,;:')
            if word:
                out.append(word)
    return out


def regex(query: str):
    """Regex equivalente (per la scansione Python). None se la query e' vuota."""
    q = (query or "").strip()
    if is_empty(q):
        return None
    if not has_wildcard(q):
        return re.compile(re.escape(q), re.IGNORECASE)
    pieces = [re.escape(p) for p in _pieces(q)]
    if not pieces:
        return None
    return re.compile(".+?".join(pieces), re.IGNORECASE)


def name_rank(name: str, query: str) -> int:
    """Rilevanza sul nome: 0 identico/ottimo, 1 inizio, 2 contiene, 3 no."""
    n = (name or "").lower()
    q = (query or "").strip().lower()
    if is_empty(q):
        return 3
    if not has_wildcard(q):
        if n == q:
            return 0
        if n.startswith(q):
            return 1
        return 2 if q in n else 3
    rx = regex(q)
    if rx is None or not rx.search(n):
        return 3
    pieces = _pieces(q)
    first = pieces[0].lower() if pieces else ""
    if first and n.startswith(first):
        return 1
    return 2
