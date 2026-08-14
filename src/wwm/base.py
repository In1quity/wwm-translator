from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

from .container import unpack_container
from .locale_text import extract_text_csv
from .project import LANG_CODES, ProjectPaths
from .version import detect_client_version

SOURCE_ORDER = ("base", "package_diff", "patch_diff")


def build_versioned_base(project: ProjectPaths, force: bool = False) -> dict[str, object]:
    version = detect_client_version(project.game_root)
    out_dir = project.base_root / version
    if out_dir.exists() and not force:
        return {"version": version, "base_dir": str(out_dir), "skipped": True}

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work"
    work.mkdir(parents=True, exist_ok=True)

    stats: dict[str, int] = {}
    merged_rows: dict[str, dict[str, str]] = {}
    targets = {
        "cn": "zh_cn",
        "en": "en",
        "target": project.target_lang,
    }
    for label, lang in targets.items():
        source_rows: dict[str, dict[str, str]] = {}
        for source in SOURCE_ORDER:
            file_name = LANG_CODES[lang] if source == "base" else f"{LANG_CODES[lang]}_diff"
            src = _source_dir(project.game_root, source) / file_name
            if not src.is_file():
                source_rows[source] = {}
                continue
            dat_dir = work / f"{label}_{source}_dat"
            text_dir = work / f"{label}_{source}_text"
            csv_path = text_dir / "TextExtractor.csv"
            unpack_container(src, dat_dir)
            extract_text_csv(dat_dir, csv_path)
            source_rows[source] = _parse_text_csv(csv_path)
            stats[f"{label}_{source}"] = len(source_rows[source])
            shutil.rmtree(dat_dir, ignore_errors=True)
            shutil.rmtree(text_dir, ignore_errors=True)

        merged = {}
        for source in SOURCE_ORDER:
            merged.update(source_rows.get(source, {}))
        merged_rows[label] = merged
        _write_tsv(out_dir / f"{label}.tsv", merged)
        stats[f"{label}_merged"] = len(merged)

    manifest = {
        "version": version,
        "target_lang": project.target_lang,
        "game_root": str(project.game_root),
        "counts": stats,
        "hashes": {
            label: _hash_rows(merged_rows[label]) for label in ("cn", "en", "target")
        },
    }
    manifest_path = project.meta_path
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    return {"version": version, "base_dir": str(out_dir), "manifest": str(manifest_path), "counts": stats}


def _source_dir(game_root: Path, source: str) -> Path:
    if source in ("base", "package_diff"):
        return game_root / "Package" / "HD" / "oversea" / "locale"
    return game_root / "LocalData" / "Patch" / "HD" / "oversea" / "locale"


def _parse_text_csv(csv_path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter=";")
        header = next(reader, None)
        if not header:
            return rows
        id_idx = header.index("ID")
        text_idx = header.index("OriginalText")
        for row in reader:
            if len(row) <= max(id_idx, text_idx):
                continue
            row_id = row[id_idx].strip().lower()
            text = row[text_idx]
            if row_id:
                rows[row_id] = text
    return rows


def _write_tsv(path: Path, rows: dict[str, str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(["ID", "OriginalText"])
        for row_id in sorted(rows):
            writer.writerow([row_id, rows[row_id]])


def _hash_rows(rows: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for row_id in sorted(rows):
        digest.update(row_id.encode("utf-8"))
        digest.update(b"\t")
        digest.update(rows[row_id].encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()

