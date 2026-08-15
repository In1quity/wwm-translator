from __future__ import annotations

from pathlib import Path

import pytest

from wwm.container import pack_container, unpack_container
from wwm.project import LANG_CODES, load_recent_projects


def _source_from_last_gui_project() -> Path:
    recents = load_recent_projects()
    if not recents:
        pytest.skip("No recent GUI projects found in data/recent.json")
    project = recents[0]
    file_base = LANG_CODES.get(project.target_lang)
    if not file_base:
        pytest.skip(f"Unsupported target language in recent project: {project.target_lang}")
    source = project.game_root / "Package" / "HD" / "oversea" / "locale" / file_base
    if not source.is_file():
        pytest.skip(f"Locale container not found for recent GUI project: {source}")
    return source


def test_roundtrip_translate_words_map_ru(tmp_path: Path) -> None:
    source = _source_from_last_gui_project()

    dat_dir = tmp_path / "dat"
    src_blocks = unpack_container(source, dat_dir)
    rebuilt = tmp_path / "rebuilt.bin"
    pack_container(dat_dir, rebuilt)
    rebuilt_dir = tmp_path / "rebuilt_dat"
    rebuilt_blocks = unpack_container(rebuilt, rebuilt_dir)
    assert len(src_blocks) == len(rebuilt_blocks)
    for left, right in zip(sorted(src_blocks), sorted(rebuilt_blocks), strict=True):
        assert left.read_bytes() == right.read_bytes()
