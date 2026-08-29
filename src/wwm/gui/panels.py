from __future__ import annotations

import sqlite3

from ..qa import qa_detail_message, qa_rule_category, qa_rule_title, qa_severity_rank
from ..render_preview import render_text_to_html
from ..tm import exact_candidates, fuzzy_candidates, preview_same_cn


def fill_tm_panel(
    conn: sqlite3.Connection,
    cn_text: str,
    master_overlay: dict[str, dict[str, str]],
    mine_overlay: dict[str, dict[str, str]],
    current_id: str | None,
) -> list[str]:
    items: list[str] = []
    same_cn_rows = conn.execute(
        "SELECT id, target_official FROM strings WHERE cn = ? ORDER BY id LIMIT 2000",
        (cn_text,),
    ).fetchall()
    trusted: dict[str, int] = {}
    for row in same_cn_rows:
        item = master_overlay.get((row["id"] or "").lower())
        if item is None:
            continue
        target = item.get("target", "").strip()
        if target:
            trusted[target] = trusted.get(target, 0) + 1
    if trusted:
        items.append("[master/trusted]")
        for target, hits in sorted(trusted.items(), key=lambda x: (-x[1], x[0]))[:20]:
            items.append(f"{target} (hits={hits})")

    official = {}
    for row in same_cn_rows:
        target = (row["target_official"] or "").strip()
        if target:
            official[target] = official.get(target, 0) + 1
    if official:
        items.append("[official/reference]")
        for target, hits in sorted(official.items(), key=lambda x: (-x[1], x[0]))[:20]:
            items.append(f"{target} (hits={hits})")

    draft = {}
    current_key = (current_id or "").lower()
    for row in same_cn_rows:
        row_id = (row["id"] or "").lower()
        if row_id == current_key:
            continue
        item = mine_overlay.get(row_id)
        if item is None:
            continue
        if (item.get("cn") or "") != cn_text:
            continue
        if item.get("state", "ours") in {"approved", "rejected"}:
            continue
        target = (item.get("target", "") or "").strip()
        if target:
            draft[target] = draft.get(target, 0) + 1
    if draft:
        items.append("[my/draft]")
        for target, hits in sorted(draft.items(), key=lambda x: (-x[1], x[0]))[:20]:
            items.append(f"{target} (hits={hits})")

    if not items:
        items.append("[master/trusted] no suggestions")

    for row in exact_candidates(conn, cn_text, 10):
        items.append(f"[exact-db] {row['target']} (hits={row['hits']})")
    for src, target, score in fuzzy_candidates(conn, cn_text, threshold=82, limit=12):
        items.append(f"[fuzzy:{score}%] {target} <= {src[:70]}")
    return items


def fill_glossary_panel(
    conn: sqlite3.Connection,
    cn: str,
    en: str,
    target_ours: str,
) -> list[str]:
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
    out: list[str] = []
    target_lower = (target_ours or "").casefold()
    for row in rows:
        term = row["target"] or ""
        line = f"{row['category']} | {row['en']} => {term} (strict={row['strict']})"
        if row["strict"] and term and term.casefold() not in target_lower:
            line = f"! mismatch | {line}"
        out.append(line)
    return out


def fill_qa_panel(conn: sqlite3.Connection, row_id: str) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT rule, severity, detail FROM qa_issues WHERE id = ? ORDER BY severity DESC, rule",
        (row_id,),
    ).fetchall()
    out: list[dict[str, str]] = []
    for row in rows:
        rule = str(row["rule"] or "")
        severity = str(row["severity"] or "")
        detail = str(row["detail"] or "")
        out.append(
            {
                "rule": rule,
                "rule_title": qa_rule_title(rule),
                "category": qa_rule_category(rule),
                "severity": severity,
                "detail": detail,
                "detail_message": qa_detail_message(detail),
            }
        )
    out.sort(
        key=lambda item: (
            qa_severity_rank(item.get("severity", "")),
            item.get("category", ""),
            item.get("rule_title", ""),
            item.get("detail_message", ""),
        )
    )
    return out


def fill_qa_overview_panel(
    conn: sqlite3.Connection, per_rule_limit: int = 300
) -> list[dict[str, object]]:
    groups = conn.execute(
        """
        SELECT q.rule, q.severity, COUNT(*) AS total
        FROM qa_issues q
        GROUP BY q.rule, q.severity
        ORDER BY
            CASE q.severity
                WHEN 'error' THEN 0
                WHEN 'warning' THEN 1
                ELSE 2
            END,
            q.rule
        """
    ).fetchall()
    out: list[dict[str, object]] = []
    for group in groups:
        rule = str(group["rule"] or "")
        severity = str(group["severity"] or "")
        rows = conn.execute(
            """
            SELECT q.id, q.detail
            FROM qa_issues q
            WHERE q.rule = ? AND q.severity = ?
            ORDER BY q.id
            LIMIT ?
            """,
            (rule, severity, per_rule_limit),
        ).fetchall()
        decoded_items = [
            (
                str(row["id"] or ""),
                str(row["detail"] or ""),
                qa_detail_message(str(row["detail"] or "")),
            )
            for row in rows
        ]
        out.append(
            {
                "rule": rule,
                "rule_title": qa_rule_title(rule),
                "category": qa_rule_category(rule),
                "severity": severity,
                "total": int(group["total"] or 0),
                "items": decoded_items,
            }
        )
    out.sort(
        key=lambda item: (
            qa_severity_rank(str(item.get("severity", ""))),
            str(item.get("category", "")),
            str(item.get("rule_title", "")),
        )
    )
    return out


def fill_same_source_panel(conn: sqlite3.Connection, source_id: str) -> list[tuple[str, str]]:
    rows = preview_same_cn(conn, source_id, 500)
    return [
        (
            f"{row['id']} | EN={row['en'][:35]} | target_official={row['target_official'][:35]}",
            row["id"],
        )
        for row in rows
    ]


def render_preview_html(text: str) -> tuple[str, list[str]]:
    html, warnings = render_text_to_html(text)
    wrapped = (
        "<html><body style='font-family:Segoe UI,Arial;font-size:11pt;'>"
        f"{html}"
        "</body></html>"
    )
    return wrapped, warnings
