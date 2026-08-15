from __future__ import annotations

import csv
import hashlib
from pathlib import Path

OVERLAY_COLUMNS = ["ID", "cn_hash", "state", "target", "needs_context", "notes"]
TRANSLATION_COLUMNS = ["ID", "cn_hash", "state", "target", "cn", "en", "needs_context", "notes"]


def cn_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_overlay(path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return out
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        next(reader, None)
        for row in reader:
            if len(row) < 4:
                continue
            row_id, saved_hash, state, ru = row[:4]
            row_id = row_id.strip().lower()
            if not row_id:
                continue
            needs_context = "0"
            notes = ""
            if len(row) > 4:
                needs_context = "1" if str(row[4]).strip().lower() in ("1", "true", "yes") else "0"
            if len(row) > 5:
                notes = row[5] or ""
            out[row_id] = {
                "cn_hash": saved_hash.strip(),
                "state": state.strip() or "ours",
                "target": ru,
                "needs_context": needs_context,
                "notes": notes,
            }
    return out


def save_overlay(path: Path, rows: dict[str, dict[str, str]]) -> dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(OVERLAY_COLUMNS)
        for row_id in sorted(rows):
            item = rows[row_id]
            writer.writerow(
                [
                    row_id,
                    item.get("cn_hash", ""),
                    item.get("state", "ours"),
                    item.get("target", ""),
                    "1" if item.get("needs_context", "0") in ("1", "true", "yes") else "0",
                    item.get("notes", ""),
                ]
            )
    return {"rows": len(rows)}


def load_translation_rows(path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return out
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        next(reader, None)
        for row in reader:
            if len(row) < 4:
                continue
            row_id = (row[0] or "").strip().lower()
            if not row_id:
                continue
            cn = row[4] if len(row) > 4 else ""
            en = row[5] if len(row) > 5 else ""
            out[row_id] = {
                "cn_hash": (row[1] or "").strip(),
                "state": (row[2] or "").strip() or "ours",
                "target": row[3] or "",
                "cn": cn or "",
                "en": en or "",
                "needs_context": (
                    "1"
                    if len(row) > 6 and str(row[6]).strip().lower() in ("1", "true", "yes")
                    else "0"
                ),
                "notes": (row[7] if len(row) > 7 else "") or "",
            }
    return out


def save_translation_rows(path: Path, rows: dict[str, dict[str, str]]) -> dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(TRANSLATION_COLUMNS)
        for row_id in sorted(rows):
            item = rows[row_id]
            writer.writerow(
                [
                    row_id,
                    item.get("cn_hash", ""),
                    item.get("state", "ours"),
                    item.get("target", ""),
                    item.get("cn", ""),
                    item.get("en", ""),
                    "1" if item.get("needs_context", "0") in ("1", "true", "yes") else "0",
                    item.get("notes", ""),
                ]
            )
    return {"rows": len(rows)}


def merge_master_rows(
    master_rows: dict[str, dict[str, str]],
    mine_rows: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    out = normalize_master_rows(master_rows)
    for row_id, item in mine_rows.items():
        if item.get("state", "") != "approved":
            continue
        target_text = item.get("target", "")
        if not target_text.strip():
            if row_id not in out:
                continue
            # Approve with empty "mine" confirms existing master text.
            continue
        out[row_id] = {
            "cn_hash": item.get("cn_hash", ""),
            "state": "ours",
            "target": target_text,
            "needs_context": "1" if item.get("needs_context", "0") in ("1", "true", "yes") else "0",
            "notes": item.get("notes", ""),
        }
    return out


def normalize_master_state(state: str) -> str:
    cleaned = (state or "").strip().lower()
    if cleaned in {"approved", "rejected"}:
        return "ours"
    return cleaned or "ours"


def normalize_master_rows(rows: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row_id, item in rows.items():
        out[row_id] = {
            "cn_hash": item.get("cn_hash", ""),
            "state": normalize_master_state(item.get("state", "ours")),
            "target": item.get("target", ""),
            "needs_context": "1" if item.get("needs_context", "0") in ("1", "true", "yes") else "0",
            "notes": item.get("notes", ""),
        }
    return out


def is_mine_layer_active(item: dict[str, str] | None) -> bool:
    if not item:
        return False
    if (item.get("target", "") or "").strip():
        return True
    if item.get("state", "ours") in {"approved", "rejected", "notranslate"}:
        return True
    return False


def reset_review(item: dict[str, str]) -> dict[str, str]:
    out = dict(item)
    if out.get("state", "ours") in {"approved", "rejected"}:
        out["state"] = "ours"
    return out
