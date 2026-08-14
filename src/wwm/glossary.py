from __future__ import annotations

import csv
from pathlib import Path

from .db import open_db

GLOSSARY_COLUMNS = ["CN", "EN", "Target", "Category", "Strict"]


def load_glossary_to_db(db_path: Path, glossary_path: Path) -> dict[str, int]:
    conn = open_db(db_path)
    conn.execute("DELETE FROM glossary")
    count = 0
    if glossary_path.is_file():
        with glossary_path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh, delimiter="\t")
            next(reader, None)
            payload = []
            for row in reader:
                if len(row) < 5:
                    continue
                cn, en, target, category, strict = row[:5]
                payload.append((cn.strip(), en.strip(), target.strip(), category.strip(), int(strict or 0)))
                count += 1
            if payload:
                conn.executemany("INSERT INTO glossary(cn, en, target, category, strict) VALUES(?, ?, ?, ?, ?)", payload)
    conn.commit()
    conn.close()
    return {"rows": count}


def export_glossary_from_db(db_path: Path, glossary_path: Path) -> dict[str, int]:
    conn = open_db(db_path)
    rows = conn.execute("SELECT cn, en, target, category, strict FROM glossary ORDER BY category, en, cn").fetchall()
    glossary_path.parent.mkdir(parents=True, exist_ok=True)
    with glossary_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(GLOSSARY_COLUMNS)
        for row in rows:
            writer.writerow([row["cn"], row["en"], row["target"], row["category"], str(row["strict"])])
    conn.close()
    return {"rows": len(rows)}

