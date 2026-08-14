from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .base import build_versioned_base
from .build import build_translation_release
from .db import rebuild_cache
from .overlay import load_overlay, load_translation_rows
from .project import LANG_CODES, open_project
from .qa import run_qa
from .version import detect_client_version


def _path(value: str) -> Path:
    return Path(value).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="WWM standalone translator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_project = sub.add_parser("project", help="Create or open translator project")
    p_project.add_argument("--game-root", required=True, help="Game root folder")
    p_project.add_argument("--lang", required=True, choices=sorted(LANG_CODES.keys()), help="Target language code")

    p_extract = sub.add_parser("extract", help="Extract CN/EN/target into project DB")
    p_extract.add_argument("--game-root", required=True, help="Game root folder")
    p_extract.add_argument("--lang", required=True, choices=sorted(LANG_CODES.keys()), help="Target language code")
    p_extract.add_argument("--force", action="store_true", help="Force rebuild extracted base")

    p_qa = sub.add_parser("qa", help="Run QA for project")
    p_qa.add_argument("--game-root", required=True, help="Game root folder")
    p_qa.add_argument("--lang", required=True, choices=sorted(LANG_CODES.keys()), help="Target language code")
    p_qa.add_argument("--master", default="", help="Optional master translation TSV")

    p_export = sub.add_parser("export", help="Export translated locale files")
    p_export.add_argument("--game-root", required=True, help="Game root folder")
    p_export.add_argument("--lang", required=True, choices=sorted(LANG_CODES.keys()), help="Target language code")
    p_export.add_argument("--output", required=True, help="Output directory for translated files")
    p_export.add_argument("--master", default="", help="Optional master translation TSV")

    p_gui = sub.add_parser("gui", help="Run desktop translator GUI")
    p_gui.add_argument("--game-root", default="", help="Optional game root folder")
    p_gui.add_argument("--lang", default="", choices=[""] + sorted(LANG_CODES.keys()), help="Optional target language")

    args = parser.parse_args()
    if args.cmd == "project":
        project = open_project(_path(args.game_root), args.lang)
        version = detect_client_version(project.game_root)
        print(
            json.dumps(
                {
                    "project_dir": str(project.project_dir),
                    "db_path": str(project.db_path),
                    "my_translation_path": str(project.my_translation_path),
                    "client_version": version,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.cmd == "extract":
        project = open_project(_path(args.game_root), args.lang)
        base_result = build_versioned_base(project, force=bool(args.force))
        rebuild_result = rebuild_cache(
            project.db_path,
            Path(base_result["base_dir"]),
            str(base_result["version"]),
            project.target_lang,
            project.game_root,
        )
        result = {"project_dir": str(project.project_dir), "base": base_result, "cache": rebuild_result}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "qa":
        project = open_project(_path(args.game_root), args.lang)
        overlay = load_translation_rows(project.my_translation_path)
        if args.master:
            master = load_overlay(_path(args.master))
            for row_id, item in master.items():
                overlay.setdefault(row_id, item)
        result = run_qa(project.db_path, overlay, project.target_lang)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "export":
        project = open_project(_path(args.game_root), args.lang)
        overlay = load_translation_rows(project.my_translation_path)
        if args.master:
            master = load_overlay(_path(args.master))
            for row_id, item in master.items():
                overlay.setdefault(row_id, item)
        result = build_translation_release(project, _path(args.output), overlay)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "gui":
        from .gui.app import main as gui_main

        argv = [sys.argv[0]]
        if args.game_root:
            argv.extend(["--game-root", args.game_root])
        if args.lang:
            argv.extend(["--target-lang", args.lang])
        sys.argv = argv
        return int(gui_main())
    raise RuntimeError(f"Unhandled command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())

