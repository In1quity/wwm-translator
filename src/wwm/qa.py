from __future__ import annotations

import re
from typing import Any

from .db import open_db
from .overlay import cn_hash
from .render_preview import render_text_to_html

PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}")
LINK_TAG_RE = re.compile(r"<[^<>|]+\|[^<>|]+\|[^<>|]+\|[^<>|]+>")
FORBIDDEN_XML_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9_:-]*>")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

ERROR_CODE_RUSSIAN_AFTER_HASH = "01"
ERROR_CODE_CLOSING_TAG_WITHOUT_OPENING = "02"
ERROR_CODE_OPENING_TAG_WITHOUT_CLOSING = "03"
ERROR_CODE_LINK_TAG_INVALID = "04"
ERROR_CODE_UNBALANCED_BRACES = "05"
ERROR_CODE_CLOSING_BRACE_WITHOUT_OPENING = "06"
ERROR_CODE_OPENING_BRACE_WITHOUT_CLOSING = "07"
ERROR_CODE_FORBIDDEN_XML_TAG = "08"


def check_row(
    row_id: str,
    cn: str,
    en: str,
    target: str,
    glossary_rows: list[Any],
    target_lang: str = "",
) -> list[tuple[str, str, str, str]]:
    payload: list[tuple[str, str, str, str]] = []
    _check_placeholders(payload, row_id, cn, target)
    _check_tags(payload, row_id, cn, target)
    _check_forbidden_xml_tags(payload, row_id, target)
    _check_lang(payload, row_id, en, target, target_lang)
    _check_glossary(payload, row_id, cn, en, target, glossary_rows)
    _check_render_tags(payload, row_id, target)
    return payload


def run_qa(db_path, overlay: dict[str, dict[str, str]], target_lang: str) -> dict[str, int]:
    conn = open_db(db_path)
    conn.execute("DELETE FROM qa_issues")
    rows = conn.execute("SELECT id, cn, en, target_official FROM strings")
    glossary = conn.execute("SELECT cn, en, target FROM glossary WHERE strict = 1").fetchall()
    payload: list[tuple[str, str, str, str]] = []
    rows_count = 0
    for row in rows:
        rows_count += 1
        item = overlay.get((row["id"] or "").lower())
        target = row["target_official"] or ""
        if item and item.get("cn_hash", "") == cn_hash(row["cn"] or ""):
            target = item.get("target", "")
        payload.extend(check_row(row["id"], row["cn"], row["en"], target, glossary, target_lang))
        if len(payload) >= 2000:
            conn.executemany(
                "INSERT OR REPLACE INTO qa_issues(id, rule, severity, detail) VALUES(?, ?, ?, ?)",
                payload,
            )
            payload.clear()
    if payload:
        conn.executemany(
            "INSERT OR REPLACE INTO qa_issues(id, rule, severity, detail) VALUES(?, ?, ?, ?)",
            payload,
        )
    _add_cn_conflicts(conn, overlay)
    conn.commit()
    total = int(conn.execute("SELECT COUNT(*) FROM qa_issues").fetchone()[0])
    conn.close()
    return {"rows": rows_count, "issues": total}


def check_row_into_db(
    conn,
    row_id: str,
    overlay: dict[str, dict[str, str]],
    target_lang: str,
) -> dict[str, int]:
    row = conn.execute(
        "SELECT id, cn, en, target_official FROM strings WHERE id = ?",
        (row_id,),
    ).fetchone()
    if row is None:
        return {"rows": 0, "issues": 0}
    glossary = conn.execute("SELECT cn, en, target FROM glossary WHERE strict = 1").fetchall()
    item = overlay.get((row["id"] or "").lower())
    target = row["target_official"] or ""
    if item and item.get("cn_hash", "") == cn_hash(row["cn"] or ""):
        target = item.get("target", "")
    payload = check_row(row["id"], row["cn"], row["en"], target, glossary, target_lang)
    conn.execute("DELETE FROM qa_issues WHERE id = ?", (row_id,))
    if payload:
        conn.executemany(
            "INSERT OR REPLACE INTO qa_issues(id, rule, severity, detail) VALUES(?, ?, ?, ?)",
            payload,
        )
    conn.commit()
    return {"rows": 1, "issues": len(payload)}


def run_qa_on_map(
    conn,
    final_map: dict[str, str],
    target_lang: str,
    source_map: dict[str, str] | None = None,
) -> dict[str, object]:
    glossary = conn.execute("SELECT cn, en, target FROM glossary WHERE strict = 1").fetchall()
    rows = conn.execute("SELECT id, cn, en FROM strings").fetchall()
    payload: list[tuple[str, str, str, str]] = []
    source_totals = {"master": 0, "official": 0, "empty": 0}
    for row in rows:
        row_id = (row["id"] or "").lower()
        target = final_map.get(row_id, "")
        source = (source_map or {}).get(row_id, "unknown")
        if source in source_totals:
            source_totals[source] += 1
        payload.extend(check_row(row["id"], row["cn"], row["en"], target, glossary, target_lang))
    critical = [item for item in payload if item[2] == "error"]
    critical_items_with_source: list[tuple[str, str, str, str, str]] = []
    for row_id, rule, severity, detail in critical[:100]:
        source = (source_map or {}).get((row_id or "").lower(), "unknown")
        critical_items_with_source.append((row_id, rule, severity, detail, source))
    return {
        "rows": len(rows),
        "issues": len(payload),
        "critical": len(critical),
        "critical_items": critical_items_with_source,
        "source_totals": source_totals,
    }


def _check_placeholders(
    payload: list[tuple[str, str, str, str]], row_id: str, cn: str, target: str
) -> None:
    if sorted(set(PLACEHOLDER_RE.findall(cn or ""))) != sorted(
        set(PLACEHOLDER_RE.findall(target or ""))
    ):
        payload.append((row_id, "placeholder_mismatch", "error", ERROR_CODE_UNBALANCED_BRACES))


def _check_tags(
    payload: list[tuple[str, str, str, str]], row_id: str, cn: str, target: str
) -> None:
    if len(LINK_TAG_RE.findall(cn or "")) != len(LINK_TAG_RE.findall(target or "")):
        payload.append((row_id, "link_tag_count_mismatch", "error", ERROR_CODE_LINK_TAG_INVALID))


def _check_forbidden_xml_tags(
    payload: list[tuple[str, str, str, str]], row_id: str, target: str
) -> None:
    bad = FORBIDDEN_XML_TAG_RE.search(target or "")
    if bad is None:
        return
    payload.append((row_id, "xml_tag_forbidden", "error", ERROR_CODE_FORBIDDEN_XML_TAG))


def _check_lang(
    payload: list[tuple[str, str, str, str]], row_id: str, en: str, target: str, target_lang: str
) -> None:
    if target and en and target == en:
        payload.append((row_id, "target_equals_en", "warning", "target equals en"))
    if target_lang not in ("zh_cn", "zh_tw") and CJK_RE.search(target or ""):
        payload.append((row_id, "target_has_cjk", "warning", "target contains chinese"))


def _check_glossary(
    payload: list[tuple[str, str, str, str]],
    row_id: str,
    cn: str,
    en: str,
    target: str,
    glossary_rows,
) -> None:
    for item in glossary_rows:
        cn_term = _field(item, "cn", 0)
        en_term = _field(item, "en", 1)
        ru_term = _field(item, "ru", 2)
        if (cn_term and cn_term in (cn or "")) or (en_term and en_term in (en or "")):
            if ru_term and ru_term not in (target or ""):
                payload.append((row_id, "glossary_term_missing", "warning", ru_term))
                return


def _check_render_tags(payload: list[tuple[str, str, str, str]], row_id: str, target: str) -> None:
    _html, warnings = render_text_to_html(target or "")
    for warning in warnings:
        payload.append((row_id, "broken_tag", "warning", warning))


def _field(item: Any, key: str, index: int) -> str:
    if isinstance(item, dict):
        return str(item.get(key, "") or "")
    if hasattr(item, "keys") and key in item.keys():
        return str(item[key] or "")
    if isinstance(item, tuple | list) and len(item) > index:
        return str(item[index] or "")
    return ""


def _add_cn_conflicts(conn, overlay: dict[str, dict[str, str]]) -> None:
    # Two-pass streaming approach to avoid loading all rows/targets into memory.
    cn_first_target: dict[str, str] = {}
    cn_conflicted: set[str] = set()

    for row in conn.execute("SELECT id, cn, target_official FROM strings WHERE cn != ''"):
        row_id = (row["id"] or "").lower()
        item = overlay.get(row_id)
        target = row["target_official"] or ""
        if item and item.get("cn_hash", "") == cn_hash(row["cn"] or ""):
            target = item.get("target", "") or target
        if not target:
            continue
        cn_text = row["cn"] or ""
        first = cn_first_target.get(cn_text)
        if first is None:
            cn_first_target[cn_text] = target
        elif first != target:
            cn_conflicted.add(cn_text)

    if not cn_conflicted:
        return

    payload: list[tuple[str, str, str, str]] = []
    for row in conn.execute("SELECT id, cn FROM strings WHERE cn != ''"):
        cn_text = row["cn"] or ""
        if cn_text not in cn_conflicted:
            continue
        payload.append(
            (
                row["id"],
                "cn_multiple_target_variants",
                "warning",
                "same CN has multiple target variants",
            )
        )
        if len(payload) >= 4000:
            conn.executemany(
                "INSERT OR IGNORE INTO qa_issues(id, rule, severity, detail) VALUES(?, ?, ?, ?)",
                payload,
            )
            payload.clear()
    if payload:
        conn.executemany(
            "INSERT OR IGNORE INTO qa_issues(id, rule, severity, detail) VALUES(?, ?, ?, ?)",
            payload,
        )
