from __future__ import annotations

import re
from typing import Any

from .db import open_db
from .overlay import cn_hash
from .render_preview import render_text_to_html

PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}")
LINK_TAG_RE = re.compile(r"<[^<>|]+\|[^<>|]+\|[^<>|]+\|[^<>|]+>")
SINGLE_COLOR_TAG_RE = re.compile(r"#([A-Za-z])(?![A-Za-z0-9])")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_ALLOWED_CN_TAGS_CACHE: dict[str, set[str]] = {}
_ALLOWED_CN_COLOR_TAGS_CACHE: dict[str, set[str]] = {}

ERROR_CODE_RUSSIAN_AFTER_HASH = "01"
ERROR_CODE_CLOSING_TAG_WITHOUT_OPENING = "02"
ERROR_CODE_OPENING_TAG_WITHOUT_CLOSING = "03"
ERROR_CODE_LINK_TAG_INVALID = "04"
ERROR_CODE_UNBALANCED_BRACES = "05"
ERROR_CODE_CLOSING_BRACE_WITHOUT_OPENING = "06"
ERROR_CODE_OPENING_BRACE_WITHOUT_CLOSING = "07"
ERROR_CODE_FORBIDDEN_XML_TAG = "08"
ERROR_CODE_COLOR_TAG_FORBIDDEN = "09"
ERROR_CODE_SINGLE_ANGLE_TAG_SUSPECT = "10"

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

QA_RULE_META: dict[str, dict[str, str]] = {
    "placeholder_mismatch": {
        "category": "structure",
        "title": "Placeholder mismatch",
    },
    "link_tag_count_mismatch": {
        "category": "tags",
        "title": "Link tag count mismatch",
    },
    "xml_tag_forbidden": {
        "category": "tags",
        "title": "Forbidden XML-like tag",
    },
    "angle_tag_suspect": {
        "category": "tags",
        "title": "Single angle tag needs review",
    },
    "color_tag_forbidden": {
        "category": "tags",
        "title": "Forbidden single-letter color tag",
    },
    "target_equals_en": {
        "category": "language",
        "title": "Target equals EN source",
    },
    "target_has_cjk": {
        "category": "language",
        "title": "Unexpected CJK in target",
    },
    "glossary_term_missing": {
        "category": "glossary",
        "title": "Missing strict glossary term",
    },
    "broken_tag": {
        "category": "render",
        "title": "Rendered preview warning",
    },
    "cn_multiple_target_variants": {
        "category": "consistency",
        "title": "CN has multiple target variants",
    },
}

ERROR_CODE_META: dict[str, str] = {
    ERROR_CODE_RUSSIAN_AFTER_HASH: "Cyrillic text starts immediately after '#' marker.",
    ERROR_CODE_CLOSING_TAG_WITHOUT_OPENING: "Closing tag appears without matching opening tag.",
    ERROR_CODE_OPENING_TAG_WITHOUT_CLOSING: "Opening tag appears without matching closing tag.",
    ERROR_CODE_LINK_TAG_INVALID: "Broken or mismatched game link tag structure.",
    ERROR_CODE_UNBALANCED_BRACES: "Placeholder sets differ between source and target.",
    ERROR_CODE_CLOSING_BRACE_WITHOUT_OPENING: (
        "Closing brace appears without matching opening brace."
    ),
    ERROR_CODE_OPENING_BRACE_WITHOUT_CLOSING: (
        "Opening brace appears without matching closing brace."
    ),
    ERROR_CODE_FORBIDDEN_XML_TAG: "Raw XML-like tags are not allowed in translation text.",
    ERROR_CODE_COLOR_TAG_FORBIDDEN: "Single-letter color code is not allowed for this CN set.",
    ERROR_CODE_SINGLE_ANGLE_TAG_SUSPECT: (
        "Single angle-bracket tag may be valid term markup; review manually."
    ),
    "same CN has multiple target variants": (
        "Identical CN source text has multiple target translation variants."
    ),
    "target equals en": "Target text is identical to EN source.",
    "target contains chinese": "Target text still contains CJK characters.",
    "opening color tag without #E": "Color tag is opened but never closed with #E.",
    "closing #E without open tag": "Closing #E appears without an opening color tag.",
    "closing $E without open $S": "Closing $E appears without an opening $S.",
    "opening $S without closing $E": "Conditional block starts with $S but never closes with $E.",
    "opening < link tag without closing >": "Link tag starts with '<' but has no closing '>'.",
}


def qa_rule_category(rule: str) -> str:
    return QA_RULE_META.get(rule, {}).get("category", "other")


def qa_rule_title(rule: str) -> str:
    return QA_RULE_META.get(rule, {}).get("title", rule.replace("_", " "))


def qa_detail_message(detail: str) -> str:
    if not detail:
        return ""
    if detail.startswith("unknown tag #"):
        return "Unknown # tag marker in text."
    return ERROR_CODE_META.get(detail, detail)


def qa_severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.get((severity or "").strip().lower(), 99)


def check_row(
    row_id: str,
    cn: str,
    en: str,
    target: str,
    glossary_rows: list[Any],
    target_lang: str = "",
) -> list[tuple[str, str, str, str]]:
    return _check_row_with_allowed_tags(
        row_id=row_id,
        cn=cn,
        en=en,
        target=target,
        glossary_rows=glossary_rows,
        target_lang=target_lang,
        allowed_tag_names=_extract_tag_names(cn or ""),
        allowed_color_tags=_extract_single_color_tags(cn or ""),
    )


def _check_row_with_allowed_tags(
    row_id: str,
    cn: str,
    en: str,
    target: str,
    glossary_rows: list[Any],
    target_lang: str,
    allowed_tag_names: set[str],
    allowed_color_tags: set[str],
) -> list[tuple[str, str, str, str]]:
    payload: list[tuple[str, str, str, str]] = []
    _check_placeholders(payload, row_id, cn, target)
    _check_tags(payload, row_id, cn, target)
    _check_forbidden_xml_tags(payload, row_id, cn, target, allowed_tag_names)
    _check_single_letter_color_tags(payload, row_id, cn, target, allowed_color_tags)
    _check_lang(payload, row_id, en, target, target_lang)
    _check_glossary(payload, row_id, cn, en, target, glossary_rows)
    _check_render_tags(payload, row_id, target)
    return payload


def run_qa(db_path, overlay: dict[str, dict[str, str]], target_lang: str) -> dict[str, int]:
    conn = open_db(db_path)
    conn.execute("DELETE FROM qa_issues")
    allowed_tag_names = _collect_allowed_cn_tag_names(conn)
    allowed_color_tags = _collect_allowed_cn_single_color_tags(conn)
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
        row_allowed_tags = _extract_tag_names(row["cn"] or "") | allowed_tag_names
        row_allowed_colors = _extract_single_color_tags(row["cn"] or "") | allowed_color_tags
        payload.extend(
            _check_row_with_allowed_tags(
                row_id=row["id"],
                cn=row["cn"],
                en=row["en"],
                target=target,
                glossary_rows=glossary,
                target_lang=target_lang,
                allowed_tag_names=row_allowed_tags,
                allowed_color_tags=row_allowed_colors,
            )
        )
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
    allowed_tag_names = _collect_allowed_cn_tag_names(conn)
    allowed_color_tags = _collect_allowed_cn_single_color_tags(conn)
    item = overlay.get((row["id"] or "").lower())
    target = row["target_official"] or ""
    if item and item.get("cn_hash", "") == cn_hash(row["cn"] or ""):
        target = item.get("target", "")
    row_allowed_tags = _extract_tag_names(row["cn"] or "") | allowed_tag_names
    row_allowed_colors = _extract_single_color_tags(row["cn"] or "") | allowed_color_tags
    payload = _check_row_with_allowed_tags(
        row_id=row["id"],
        cn=row["cn"],
        en=row["en"],
        target=target,
        glossary_rows=glossary,
        target_lang=target_lang,
        allowed_tag_names=row_allowed_tags,
        allowed_color_tags=row_allowed_colors,
    )
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
    allowed_tag_names = _collect_allowed_cn_tag_names(conn)
    allowed_color_tags = _collect_allowed_cn_single_color_tags(conn)
    payload: list[tuple[str, str, str, str]] = []
    source_totals = {"master": 0, "official": 0, "empty": 0}
    for row in rows:
        row_id = (row["id"] or "").lower()
        target = final_map.get(row_id, "")
        source = (source_map or {}).get(row_id, "unknown")
        if source in source_totals:
            source_totals[source] += 1
        row_allowed_tags = _extract_tag_names(row["cn"] or "") | allowed_tag_names
        row_allowed_colors = _extract_single_color_tags(row["cn"] or "") | allowed_color_tags
        payload.extend(
            _check_row_with_allowed_tags(
                row_id=row["id"],
                cn=row["cn"],
                en=row["en"],
                target=target,
                glossary_rows=glossary,
                target_lang=target_lang,
                allowed_tag_names=row_allowed_tags,
                allowed_color_tags=row_allowed_colors,
            )
        )
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
    payload: list[tuple[str, str, str, str]],
    row_id: str,
    cn: str,
    target: str,
    allowed_tag_names: set[str] | None = None,
) -> None:
    cn_tag_names = _extract_tag_names(cn or "")
    if allowed_tag_names:
        cn_tag_names |= allowed_tag_names
    for token in _iter_angle_tokens(target or ""):
        # Link-like angle tags are validated by link_tag_count_mismatch;
        # do not duplicate them as forbidden XML-like tags.
        if "|" in token:
            continue
        if _is_allowed_param_link_tag(token):
            continue
        tag_name = _extract_tag_name(token)
        if tag_name is None:
            payload.append(
                (row_id, "angle_tag_suspect", "warning", ERROR_CODE_SINGLE_ANGLE_TAG_SUSPECT)
            )
            return
        if tag_name and tag_name in cn_tag_names:
            continue
        payload.append((row_id, "xml_tag_forbidden", "error", ERROR_CODE_FORBIDDEN_XML_TAG))
        return


def _check_single_letter_color_tags(
    payload: list[tuple[str, str, str, str]],
    row_id: str,
    cn: str,
    target: str,
    allowed_color_tags: set[str],
) -> None:
    row_colors = _extract_single_color_tags(cn or "")
    allow = {tag.upper() for tag in allowed_color_tags} | {tag.upper() for tag in row_colors}
    for tag in _extract_single_color_tags(target or ""):
        upper = tag.upper()
        if upper == "E":
            continue
        if upper not in allow:
            payload.append((row_id, "color_tag_forbidden", "error", ERROR_CODE_COLOR_TAG_FORBIDDEN))
            return


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
        payload.append((row_id, "broken_tag", _render_warning_severity(warning), warning))


def _field(item: Any, key: str, index: int) -> str:
    if isinstance(item, dict):
        return str(item.get(key, "") or "")
    if hasattr(item, "keys") and key in item.keys():
        return str(item[key] or "")
    if isinstance(item, tuple | list) and len(item) > index:
        return str(item[index] or "")
    return ""


def _render_warning_severity(message: str) -> str:
    text = (message or "").strip().lower()
    critical_markers = (
        "without open",
        "without closing",
        "opening color tag without #e",
        "opening < link tag without closing >",
    )
    if any(marker in text for marker in critical_markers):
        return "error"
    return "warning"


def _iter_angle_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    stack: list[int] = []
    for idx, ch in enumerate(text):
        if ch == "<":
            stack.append(idx)
            continue
        if ch != ">" or not stack:
            continue
        start = stack.pop()
        tokens.append(text[start : idx + 1])
    return tokens


def _extract_tag_name(token: str) -> str | None:
    match = re.fullmatch(
        r"<\s*/?\s*([A-Za-z][A-Za-z0-9_:\-]*)\b[^>]*>",
        token.strip(),
    )
    if match is None:
        return None
    return str(match.group(1))


def _extract_tag_names(text: str) -> set[str]:
    names: set[str] = set()
    for token in _iter_angle_tokens(text):
        tag_name = _extract_tag_name(token)
        if tag_name:
            names.add(tag_name)
    return names


def _extract_single_color_tags(text: str) -> set[str]:
    tags = {tag.upper() for tag in SINGLE_COLOR_TAG_RE.findall(text or "")}
    return {tag for tag in tags if tag != "E"}


def _is_allowed_param_link_tag(token: str) -> bool:
    if not token.startswith("<") or not token.endswith(">"):
        return False
    inner = token[1:-1]
    if not inner or "<" in inner or ">" in inner:
        return False
    parts = inner.split("|")
    if len(parts) != 4:
        return False
    return all(part.strip() != "" for part in parts)


def _db_main_path(conn) -> str:
    row = conn.execute("PRAGMA database_list").fetchone()
    if row is None:
        return ""
    try:
        return str(row[2] or "")
    except Exception:
        return ""


def _collect_allowed_cn_tag_names(conn) -> set[str]:
    cache_key = _db_main_path(conn)
    if cache_key and cache_key in _ALLOWED_CN_TAGS_CACHE:
        return _ALLOWED_CN_TAGS_CACHE[cache_key]
    names: set[str] = set()
    for row in conn.execute("SELECT cn FROM strings WHERE cn LIKE '%<%'"):
        names |= _extract_tag_names(str(row["cn"] or ""))
    if cache_key:
        _ALLOWED_CN_TAGS_CACHE[cache_key] = names
    return names


def _collect_allowed_cn_single_color_tags(conn) -> set[str]:
    cache_key = _db_main_path(conn)
    if cache_key and cache_key in _ALLOWED_CN_COLOR_TAGS_CACHE:
        return _ALLOWED_CN_COLOR_TAGS_CACHE[cache_key]
    tags: set[str] = set()
    for row in conn.execute("SELECT cn FROM strings WHERE cn LIKE '%#%'"):
        tags |= _extract_single_color_tags(str(row["cn"] or ""))
    if cache_key:
        _ALLOWED_CN_COLOR_TAGS_CACHE[cache_key] = tags
    return tags


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
                "info",
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
