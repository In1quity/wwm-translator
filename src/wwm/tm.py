from __future__ import annotations

import difflib
import sqlite3

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover
    fuzz = None


def rebuild_tm(
    conn: sqlite3.Connection,
    master_overlay: dict[str, dict[str, str]] | None = None,
) -> dict[str, int]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tm (
            cn TEXT NOT NULL,
            target TEXT NOT NULL,
            hits INTEGER NOT NULL,
            PRIMARY KEY (cn, target)
        )
        """
    )
    conn.execute("DELETE FROM tm")
    conn.execute(
        """
        INSERT INTO tm(cn, target, hits)
        SELECT cn, target_official, COUNT(*)
        FROM strings
        WHERE length(cn) > 0 AND length(target_official) > 0
        GROUP BY cn, target_official
        """
    )
    master_pairs = 0
    if master_overlay:
        for row_id, item in master_overlay.items():
            target = (item.get("target", "") or "").strip()
            if not target:
                continue
            row = conn.execute("SELECT cn FROM strings WHERE id = ?", (row_id,)).fetchone()
            if row is None:
                continue
            cn_text = (row["cn"] or "").strip()
            if not cn_text:
                continue
            conn.execute(
                """
                INSERT INTO tm(cn, target, hits)
                VALUES(?, ?, 100000)
                ON CONFLICT(cn, target) DO UPDATE SET hits = hits + 100000
                """,
                (cn_text, target),
            )
            master_pairs += 1
    conn.commit()
    pairs = int(conn.execute("SELECT COUNT(*) FROM tm").fetchone()[0])
    rows = int(
        conn.execute(
            "SELECT COUNT(*) FROM strings WHERE length(cn) > 0 AND length(target_official) > 0"
        ).fetchone()[0]
    )
    return {"pairs": pairs, "rows": rows, "master_pairs": master_pairs}


def exact_candidates(conn: sqlite3.Connection, cn_text: str, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT target, hits FROM tm WHERE cn = ? ORDER BY hits DESC, target LIMIT ?",
        (cn_text, limit),
    ).fetchall()


def fuzzy_candidates(
    conn: sqlite3.Connection, cn_text: str, threshold: int = 80, limit: int = 20
) -> list[tuple[str, str, int]]:
    rows = conn.execute("SELECT cn, target, hits FROM tm ORDER BY hits DESC LIMIT 30000").fetchall()
    found: list[tuple[str, str, int]] = []
    for row in rows:
        score = _score(cn_text, row["cn"])
        if score >= threshold:
            found.append((row["cn"], row["target"], score))
    found.sort(key=lambda item: item[2], reverse=True)
    return found[:limit]


def preview_same_cn(
    conn: sqlite3.Connection, source_id: str, limit: int = 300
) -> list[sqlite3.Row]:
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
