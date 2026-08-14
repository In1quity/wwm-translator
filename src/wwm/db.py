from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


def open_db(db_path: Path, ensure: bool = True) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    if ensure:
        ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS strings (
            id TEXT PRIMARY KEY,
            cn TEXT NOT NULL DEFAULT '',
            en TEXT NOT NULL DEFAULT '',
            target_official TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            cat_conf REAL NOT NULL DEFAULT 0.0,
            note TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_strings_category ON strings(category);
        CREATE TABLE IF NOT EXISTS qa_issues (
            id TEXT NOT NULL,
            rule TEXT NOT NULL,
            severity TEXT NOT NULL,
            detail TEXT NOT NULL,
            PRIMARY KEY (id, rule)
        );
        CREATE TABLE IF NOT EXISTS tm (
            cn TEXT NOT NULL,
            target TEXT NOT NULL,
            hits INTEGER NOT NULL,
            PRIMARY KEY (cn, target)
        );
        CREATE TABLE IF NOT EXISTS glossary (
            cn TEXT NOT NULL DEFAULT '',
            en TEXT NOT NULL DEFAULT '',
            target TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            strict INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (cn, en, target, category)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS strings_fts
        USING fts5(id UNINDEXED, cn, en, target_official, tokenize='trigram');
        """
    )
    cols = [row[1] for row in conn.execute("PRAGMA table_info(strings)").fetchall()]
    if "target_official" not in cols:
        source_target_col = "ru_official" if "ru_official" in cols else "''"
        conn.executescript(
            f"""
            CREATE TABLE strings_new (
                id TEXT PRIMARY KEY,
                cn TEXT NOT NULL DEFAULT '',
                en TEXT NOT NULL DEFAULT '',
                target_official TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                cat_conf REAL NOT NULL DEFAULT 0.0,
                note TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO strings_new(id, cn, en, target_official, category, cat_conf, note)
            SELECT id, cn, en, COALESCE({source_target_col}, ''), category, cat_conf, note
            FROM strings;
            DROP TABLE strings;
            ALTER TABLE strings_new RENAME TO strings;
            CREATE INDEX IF NOT EXISTS idx_strings_category ON strings(category);
            """
        )
    tm_cols = [row[1] for row in conn.execute("PRAGMA table_info(tm)").fetchall()]
    if "target" not in tm_cols:
        conn.executescript(
            """
            DROP TABLE IF EXISTS tm;
            CREATE TABLE tm (
                cn TEXT NOT NULL,
                target TEXT NOT NULL,
                hits INTEGER NOT NULL,
                PRIMARY KEY (cn, target)
            );
            """
        )
    gl_cols = [row[1] for row in conn.execute("PRAGMA table_info(glossary)").fetchall()]
    if "target" not in gl_cols:
        conn.executescript(
            """
            DROP TABLE IF EXISTS glossary;
            CREATE TABLE glossary (
                cn TEXT NOT NULL DEFAULT '',
                en TEXT NOT NULL DEFAULT '',
                target TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                strict INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (cn, en, target, category)
            );
            """
        )

    strings_count = conn.execute("SELECT COUNT(*) FROM strings").fetchone()[0]
    fts_count = conn.execute("SELECT COUNT(*) FROM strings_fts").fetchone()[0]
    if strings_count > 0 and fts_count == 0:
        conn.execute(
            "INSERT INTO strings_fts(rowid, id, cn, en, target_official) "
            "SELECT rowid, id, cn, en, target_official FROM strings"
        )
    conn.commit()


def rebuild_cache(
    db_path: Path,
    base_dir: Path,
    version: str,
    target_lang: str,
    game_root: Path,
) -> dict[str, int]:
    if not base_dir.is_dir():
        raise FileNotFoundError(f"Missing base snapshot: {base_dir}")
    cn = _read_tsv(base_dir / "cn.tsv")
    en = _read_tsv(base_dir / "en.tsv")
    target = _read_tsv(base_dir / "target.tsv")
    all_ids = set(cn) | set(en) | set(target)

    conn = open_db(db_path)
    conn.execute("DELETE FROM strings")
    conn.execute("DELETE FROM strings_fts")
    conn.execute("DELETE FROM qa_issues")
    batch: list[tuple[str, str, str, str]] = []
    for row_id in sorted(all_ids):
        cn_text = cn.get(row_id, "")
        en_text = en.get(row_id, "")
        target_official = target.get(row_id, "")
        batch.append((row_id, cn_text, en_text, target_official))
        if len(batch) >= 20000:
            conn.executemany(
                "INSERT INTO strings(id, cn, en, target_official) VALUES(?, ?, ?, ?)",
                batch,
            )
            batch.clear()
    if batch:
        conn.executemany(
            "INSERT INTO strings(id, cn, en, target_official) VALUES(?, ?, ?, ?)",
            batch,
        )
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('base_version', ?)", (version,))
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('target_lang', ?)", (target_lang,))
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('game_root', ?)", (str(game_root),)
    )
    conn.execute(
        "INSERT INTO strings_fts(rowid, id, cn, en, target_official) "
        "SELECT rowid, id, cn, en, target_official FROM strings"
    )
    conn.commit()
    conn.close()
    return {"rows": len(all_ids)}


def _read_tsv(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        next(reader, None)
        for row in reader:
            if len(row) >= 2:
                rows[row[0].strip().lower()] = row[1]
    return rows
