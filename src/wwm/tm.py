from __future__ import annotations

import difflib
import sqlite3
from collections import defaultdict

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover
    fuzz = None


def rebuild_tm(conn: sqlite3.Connection) -> dict[str, int]:
    conn.execute("DELETE FROM tm")
    rows = conn.execute("SELECT cn, target_official FROM strings WHERE cn != '' AND target_official != ''").fetchall()
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        counts[(row["cn"], row["target_official"])] += 1
    payload = [(cn, target, hits) for (cn, target), hits in counts.items()]
    conn.executemany("INSERT INTO tm(cn, target, hits) VALUES(?, ?, ?)", payload)
    conn.commit()
    return {"pairs": len(payload), "rows": len(rows)}


def exact_candidates(conn: sqlite3.Connection, cn_text: str, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT target, hits FROM tm WHERE cn = ? ORDER BY hits DESC, target LIMIT ?",
        (cn_text, limit),
    ).fetchall()


def fuzzy_candidates(conn: sqlite3.Connection, cn_text: str, threshold: int = 80, limit: int = 20) -> list[tuple[str, str, int]]:
    rows = conn.execute("SELECT cn, target, hits FROM tm ORDER BY hits DESC LIMIT 30000").fetchall()
    found: list[tuple[str, str, int]] = []
    for row in rows:
        score = _score(cn_text, row["cn"])
        if score >= threshold:
            found.append((row["cn"], row["target"], score))
    found.sort(key=lambda item: item[2], reverse=True)
    return found[:limit]


def preview_same_cn(conn: sqlite3.Connection, source_id: str, limit: int = 300) -> list[sqlite3.Row]:
    row = conn.execute("SELECT cn FROM strings WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        return []
    return conn.execute(
        "SELECT id, en, target_official FROM strings WHERE cn = ? ORDER BY id LIMIT ?",
        (row["cn"], limit),
    ).fetchall()


def _score(left: str, right: str) -> int:
    if fuzz is not None:
        return int(fuzz.ratio(left, right))
    return int(difflib.SequenceMatcher(a=left, b=right).ratio() * 100)

