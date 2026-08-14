from __future__ import annotations

from pathlib import Path

import pytest

from wwm.container import pack_container, unpack_container


def test_roundtrip_translate_words_map_ru(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source = repo_root / "local" / "Package" / "HD" / "oversea" / "locale" / "translate_words_map_ru"
    if not source.is_file():
        pytest.skip("local client file translate_words_map_ru not found")

    dat_dir = tmp_path / "dat"
    src_blocks = unpack_container(source, dat_dir)
    rebuilt = tmp_path / "rebuilt.bin"
    pack_container(dat_dir, rebuilt)
    rebuilt_dir = tmp_path / "rebuilt_dat"
    rebuilt_blocks = unpack_container(rebuilt, rebuilt_dir)
    assert len(src_blocks) == len(rebuilt_blocks)
    for left, right in zip(sorted(src_blocks), sorted(rebuilt_blocks), strict=True):
        assert left.read_bytes() == right.read_bytes()

