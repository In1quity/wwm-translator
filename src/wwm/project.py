from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

LANG_CODES = {
    "de": "translate_words_map_de",
    "en": "translate_words_map_en",
    "es": "translate_words_map_es",
    "fr": "translate_words_map_fr",
    "ja": "translate_words_map_ja",
    "ko": "translate_words_map_ko",
    "pt_br": "translate_words_map_pt_br",
    "ru": "translate_words_map_ru",
    "th": "translate_words_map_th",
    "vi": "translate_words_map_vi",
    "zh_cn": "translate_words_map_zh_cn",
    "zh_tw": "translate_words_map_zh_tw",
}


@dataclass
class ProjectPaths:
    data_root: Path
    project_dir: Path
    game_root: Path
    target_lang: str
    db_path: Path
    my_translation_path: Path
    meta_path: Path
    base_root: Path
    temp_root: Path


@dataclass
class RecentProject:
    game_root: Path
    target_lang: str
    project_dir: Path


def resolve_data_root(app_name: str = "WWMTranslator") -> Path:
    _ = app_name
    # For packaged app we always keep data near executable.
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent / "data"
        root.mkdir(parents=True, exist_ok=True)
        return root

    # Developer/runtime fallback outside packaged mode.
    # Keep local data in the current working directory for predictability.
    root = Path.cwd() / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def project_slug(game_root: Path, target_lang: str) -> str:
    base_name = game_root.resolve().name or "game"
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "_", base_name).strip("._-").lower()
    if not normalized:
        normalized = "game"
    return f"{normalized}_{target_lang}"


def open_project(
    game_root: Path, target_lang: str, app_name: str = "WWMTranslator"
) -> ProjectPaths:
    lang = (target_lang or "").strip().lower()
    if lang not in LANG_CODES:
        raise ValueError(f"Unsupported target language: {target_lang}")
    root = resolve_data_root(app_name)
    slug = project_slug(game_root, lang)
    project_dir = root / "projects" / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    base_root = project_dir / "base"
    base_root.mkdir(parents=True, exist_ok=True)
    temp_root = project_dir / "_tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    paths = ProjectPaths(
        data_root=root,
        project_dir=project_dir,
        game_root=game_root.resolve(),
        target_lang=lang,
        db_path=project_dir / "project.db",
        my_translation_path=project_dir / "my_translation.tsv",
        meta_path=project_dir / "project.json",
        base_root=base_root,
        temp_root=temp_root,
    )
    meta = load_project_meta(paths)
    meta.update(
        {
            "game_root": str(paths.game_root),
            "target_lang": paths.target_lang,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )
    save_project_meta(paths, meta)
    remember_project(paths)
    return paths


def load_project_meta(project: ProjectPaths) -> dict[str, object]:
    if not project.meta_path.is_file():
        return {}
    try:
        raw = json.loads(project.meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def save_project_meta(project: ProjectPaths, payload: dict[str, object]) -> None:
    project.meta_path.parent.mkdir(parents=True, exist_ok=True)
    project.meta_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def remember_project(project: ProjectPaths) -> None:
    path = project.data_root / "recent.json"
    current: list[dict[str, str]] = []
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        game_root = str(item.get("game_root", ""))
                        target_lang = str(item.get("target_lang", ""))
                        project_dir = str(item.get("project_dir", ""))
                        if game_root and target_lang and project_dir:
                            current.append(
                                {
                                    "game_root": game_root,
                                    "target_lang": target_lang,
                                    "project_dir": project_dir,
                                }
                            )
        except json.JSONDecodeError:
            current = []
    current = [x for x in current if x["project_dir"] != str(project.project_dir)]
    current.insert(
        0,
        {
            "game_root": str(project.game_root),
            "target_lang": project.target_lang,
            "project_dir": str(project.project_dir),
        },
    )
    path.write_text(json.dumps(current[:20], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_recent_projects(app_name: str = "WWMTranslator") -> list[RecentProject]:
    root = resolve_data_root(app_name)
    path = root / "recent.json"
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    out: list[RecentProject] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        game_root = Path(str(item.get("game_root", ""))).resolve()
        target_lang = str(item.get("target_lang", "")).strip().lower()
        project_dir = Path(str(item.get("project_dir", ""))).resolve()
        if not target_lang or not project_dir:
            continue
        out.append(
            RecentProject(game_root=game_root, target_lang=target_lang, project_dir=project_dir)
        )
    return out
