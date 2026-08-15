from __future__ import annotations

import sqlite3

import pytest

try:
    import PyQt6.QtGui  # noqa: F401
except ImportError as exc:
    pytest.skip(
        f"PyQt6 QtGui is unavailable in this environment: {exc}",
        allow_module_level=True,
    )

from wwm.gui.models import StringsRepository
from wwm.overlay import cn_hash


def _make_repo() -> StringsRepository:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE strings (
            id TEXT PRIMARY KEY,
            cn TEXT NOT NULL DEFAULT '',
            en TEXT NOT NULL DEFAULT '',
            target_official TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE qa_issues (
            id TEXT NOT NULL,
            rule TEXT NOT NULL,
            severity TEXT NOT NULL,
            detail TEXT NOT NULL,
            PRIMARY KEY (id, rule)
        );
        CREATE VIRTUAL TABLE strings_fts USING fts5(id UNINDEXED, cn, en, target_official);
        """
    )
    conn.execute(
        "INSERT INTO strings(id, cn, en, target_official, category) VALUES(?, ?, ?, ?, ?)",
        ("id1", "测试", "test", "Official", "other"),
    )
    return StringsRepository(conn)


def test_notes_only_mine_entry_does_not_override_state() -> None:
    repo = _make_repo()
    repo.set_overlays(
        {"id1": {"cn_hash": cn_hash("测试"), "state": "ours", "target": "Master"}},
        {
            "id1": {
                "cn_hash": cn_hash("测试"),
                "state": "ours",
                "target": "",
                "notes": "only note",
                "needs_context": "1",
            }
        },
    )
    row = repo.get_row("id1")
    assert row is not None
    assert row["state"] == "master"
    assert row["target"] == "Master"


def test_auto_approved_when_mine_equals_master() -> None:
    repo = _make_repo()
    repo.set_overlays(
        {"id1": {"cn_hash": cn_hash("测试"), "state": "ours", "target": "Master"}},
        {"id1": {"cn_hash": cn_hash("测试"), "state": "ours", "target": "Master"}},
    )
    row = repo.get_row("id1")
    assert row is not None
    assert row["state"] == "approved"
    assert row["target"] == "Master"


def test_official_match_state() -> None:
    repo = _make_repo()
    repo.set_overlays(
        {"id1": {"cn_hash": cn_hash("测试"), "state": "ours", "target": "Master"}},
        {"id1": {"cn_hash": cn_hash("测试"), "state": "ours", "target": "Official"}},
    )
    row = repo.get_row("id1")
    assert row is not None
    assert row["state"] == "official_match"
    assert row["target"] == "Official"

