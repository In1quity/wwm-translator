from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path

from .container import pack_container, unpack_container
from .locale_text import DatDocument, read_dat_document, write_dat_document
from .project import LANG_CODES, ProjectPaths


def build_translation_release(
    project: ProjectPaths,
    output_dir: Path,
    overlay_rows: dict[str, dict[str, str]],
) -> dict[str, object]:
    overlay_map = _overlay_to_map(overlay_rows)
    abs_out = output_dir.resolve()
    _validate_export_output_dir(project, abs_out)
    if abs_out.exists():
        shutil.rmtree(abs_out)
    abs_out.mkdir(parents=True, exist_ok=True)

    file_base = LANG_CODES[project.target_lang]
    targets = [
        project.game_root / "Package" / "HD" / "oversea" / "locale" / file_base,
        project.game_root / "Package" / "HD" / "oversea" / "locale" / f"{file_base}_diff",
        project.game_root
        / "LocalData"
        / "Patch"
        / "HD"
        / "oversea"
        / "locale"
        / f"{file_base}_diff",
    ]

    built_files: list[str] = []
    touched_ids = 0
    for src in targets:
        if not src.is_file():
            continue
        built, touched = _rewrite_container(project, src, abs_out, overlay_map)
        touched_ids += touched
        built_files.append(str(built))

    client_version = "unknown"
    try:
        from .version import detect_client_version

        client_version = detect_client_version(project.game_root)
    except Exception:  # noqa: BLE001
        client_version = "unknown"

    zip_path = abs_out / f"wwm-translator-{project.target_lang}-{client_version}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in abs_out.rglob("*"):
            if file.is_file() and file != zip_path:
                zf.write(file, file.relative_to(abs_out))

    return {
        "built_files": built_files,
        "touched_ids": touched_ids,
        "zip": str(zip_path),
    }


def _validate_export_output_dir(project: ProjectPaths, output_dir: Path) -> None:
    protected = [
        project.project_dir.resolve(),
        project.db_path.resolve(),
        project.base_root.resolve(),
        project.temp_root.resolve(),
    ]
    for item in protected:
        if _is_within(item, output_dir):
            raise ValueError(
                "Export directory points to project internal data. "
                "Choose another folder outside data/projects."
            )


def _rewrite_container(
    project: ProjectPaths,
    input_file: Path,
    output_root: Path,
    overlay_map: dict[str, str],
) -> tuple[Path, int]:
    raw_key = str(input_file.resolve()).encode("utf-8", errors="ignore")
    work_key = hashlib.sha1(raw_key).hexdigest()[:16]
    work = project.temp_root / "build_work" / work_key
    dat_dir = work / "dat"
    rewritten = work / "rewritten"
    dat_dir.mkdir(parents=True, exist_ok=True)
    rewritten.mkdir(parents=True, exist_ok=True)

    unpack_container(input_file, dat_dir)
    touched = 0
    for dat_file in sorted(dat_dir.glob("*.dat")):
        doc = read_dat_document(dat_file)
        if doc is None:
            shutil.copy2(dat_file, rewritten / dat_file.name)
            continue
        changed = False
        new_entries = []
        for entry in doc.entries:
            if entry.id_hex in overlay_map:
                new_text = overlay_map[entry.id_hex]
                if entry.text != new_text:
                    entry.text = new_text
                    touched += 1
                    changed = True
            new_entries.append(entry)
        out_path = rewritten / dat_file.name
        if not changed:
            shutil.copy2(dat_file, out_path)
            continue
        new_doc = DatDocument(
            file_name=doc.file_name,
            count_full=doc.count_full,
            work_blocks=doc.work_blocks,
            header_hex=doc.header_hex,
            entries=new_entries,
        )
        write_dat_document(out_path, new_doc)

    out_file = output_root / _to_release_relative(project, input_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    pack_container(rewritten, out_file)
    shutil.rmtree(work, ignore_errors=True)
    return out_file, touched


def _overlay_to_map(rows: dict[str, dict[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row_id, item in rows.items():
        state = item.get("state", "ours")
        if state == "outdated":
            continue
        text = item.get("target", "")
        if text.strip():
            out[(row_id or "").strip().lower()] = text
    return out


def _to_release_relative(project: ProjectPaths, input_file: Path) -> Path:
    parts = input_file.resolve().parts
    root_parts = project.game_root.resolve().parts
    if len(parts) >= len(root_parts) and parts[: len(root_parts)] == root_parts:
        return Path(*parts[len(root_parts) :])
    if "Package" in parts:
        idx = parts.index("Package")
        return Path(*parts[idx:])
    if "LocalData" in parts:
        idx = parts.index("LocalData")
        return Path(*parts[idx:])
    return Path(input_file.name)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
