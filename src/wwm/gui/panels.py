from __future__ import annotations

import sqlite3

from ..tm import exact_candidates, fuzzy_candidates, preview_same_cn


def fill_tm_panel(conn: sqlite3.Connection, cn_text: str) -> list[str]:
    items: list[str] = []
    for row in exact_candidates(conn, cn_text, 20):
        items.append(f"[exact] {row['target']} (hits={row['hits']})")
    for src, target, score in fuzzy_candidates(conn, cn_text, threshold=82, limit=12):
        items.append(f"[{score}%] {target} <= {src[:70]}")
    return items


def fill_glossary_panel(conn: sqlite3.Connection, cn: str, en: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT cn, en, target, category, strict
        FROM glossary
        WHERE (cn != '' AND ? LIKE '%' || cn || '%')
           OR (en != '' AND ? LIKE '%' || en || '%')
        ORDER BY strict DESC, category, en
        LIMIT 100
        """,
        (cn, en),
    ).fetchall()
    return [
        f"{row['category']} | {row['en']} => {row['target']} (strict={row['strict']})"
        for row in rows
    ]


def fill_qa_panel(conn: sqlite3.Connection, row_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT rule, severity, detail FROM qa_issues WHERE id = ? ORDER BY severity DESC, rule",
        (row_id,),
    ).fetchall()
    return [f"{row['severity']} | {row['rule']} | {row['detail']}" for row in rows]


def fill_preview_panel(conn: sqlite3.Connection, source_id: str) -> list[str]:
    rows = preview_same_cn(conn, source_id, 500)
    return [
        f"{row['id']} | EN={row['en'][:35]} | target_official={row['target_official'][:35]}"
        for row in rows
    ]
