from __future__ import annotations

import csv
import hashlib
from pathlib import Path

OVERLAY_COLUMNS = ["ID", "cn_hash", "state", "target"]
TRANSLATION_COLUMNS = ["ID", "cn_hash", "state", "target", "cn", "en"]


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
            out[row_id] = {
                "cn_hash": saved_hash.strip(),
                "state": state.strip() or "ours",
                "target": ru,
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
                [row_id, item.get("cn_hash", ""), item.get("state", "ours"), item.get("target", "")]
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
                ]
            )
    return {"rows": len(rows)}


def merge_master_rows(
    master_rows: dict[str, dict[str, str]],
    mine_rows: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    out = {row_id: dict(item) for row_id, item in master_rows.items()}
    for row_id, item in mine_rows.items():
        if item.get("state", "") != "approved":
            continue
        out[row_id] = {
            "cn_hash": item.get("cn_hash", ""),
            "state": "ours",
            "target": item.get("target", ""),
        }
    return out
