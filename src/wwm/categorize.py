from __future__ import annotations

import re
import sqlite3
from pathlib import Path

LEXICON_DIR = Path(__file__).resolve().parent / "lexicon"
PUNCT_RE = re.compile(r"[.!?。！？]")
PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}")


def _load(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


SKILLS_CN = _load(LEXICON_DIR / "skills_cn.txt")
WEAPONS_EN = _load(LEXICON_DIR / "weapons_en.txt")
SYSTEM_MARKERS = _load(LEXICON_DIR / "system_markers.txt")


def run_categorization(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT id, cn, en FROM strings").fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        cat, conf = infer_category(row["cn"] or "", row["en"] or "")
        conn.execute(
            "UPDATE strings SET category = ?, cat_conf = ? WHERE id = ?", (cat, conf, row["id"])
        )
        counts[cat] = counts.get(cat, 0) + 1
    conn.commit()
    return {"rows": len(rows), **{f"cat_{k}": v for k, v in counts.items()}}


def infer_category(cn: str, en: str) -> tuple[str, float]:
    if not en.strip() and any(marker in cn for marker in SYSTEM_MARKERS):
        return ("notranslate", 0.95)
    if any(word in cn for word in SKILLS_CN):
        return ("skill", 0.9)
    if any(word in en for word in WEAPONS_EN):
        return ("weapon", 0.82)
    if PLACEHOLDER_RE.search(cn):
        return ("format", 0.78)
    if len(cn) > 45 and PUNCT_RE.search(cn):
        return ("dialog", 0.72)
    if cn and len(cn) < 18 and not PUNCT_RE.search(cn):
        return ("ui_label", 0.62)
    return ("other", 0.4)
