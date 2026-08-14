from __future__ import annotations

import csv
import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DatEntry:
    id_hex: str
    text: str


@dataclass
class DatDocument:
    file_name: str
    count_full: int
    work_blocks: int
    header_hex: str
    entries: list[DatEntry]


def read_dat_document(dat_path: Path) -> DatDocument | None:
    with dat_path.open("rb") as fh:
        fh.seek(16)
        if fh.read(4) != b"\xdc\x96\x58\x59":
            return None
        fh.seek(0)
        count_full = struct.unpack("<I", fh.read(4))[0]
        table_offset = _table_offset(count_full)
        header_data = fh.read(table_offset - 4)
        work_blocks = (
            struct.unpack("<I", header_data[4:8])[0] if len(header_data) >= 8 else count_full
        )
        file_size = dat_path.stat().st_size
        entries: list[DatEntry] = []
        for i in range(count_full):
            entry_offset = table_offset + i * 16
            fh.seek(entry_offset)
            current = fh.tell()
            id_hex = fh.read(8).hex()
            offset = struct.unpack("<I", fh.read(4))[0]
            length = struct.unpack("<I", fh.read(4))[0]
            text = ""
            if length > 0:
                text_offset = offset + current + 8
                if 0 <= text_offset < file_size and text_offset + length <= file_size * 10:
                    fh.seek(text_offset)
                    text = fh.read(length).decode("utf-8", errors="ignore")
            entries.append(DatEntry(id_hex=id_hex, text=_escape(text)))
    return DatDocument(
        file_name=dat_path.name,
        count_full=count_full,
        work_blocks=work_blocks,
        header_hex=header_data.hex(),
        entries=entries,
    )


def write_dat_document(output_path: Path, document: DatDocument) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header_data = (
        bytes.fromhex(document.header_hex)
        if document.header_hex
        else _default_header(document.count_full, document.work_blocks)
    )
    with output_path.open("wb") as out:
        out.write(struct.pack("<I", document.count_full))
        out.write(header_data)
        table_start = out.tell()
        for _ in range(document.count_full):
            out.write(b"\x00" * 16)

        for idx, item in enumerate(document.entries):
            text_bytes = _unescape(item.text).encode("utf-8")
            text_offset = out.tell()
            out.write(text_bytes)
            row_pos = table_start + idx * 16
            rel_offset = text_offset - row_pos - 8
            current = out.tell()
            out.seek(row_pos)
            out.write(bytes.fromhex(item.id_hex))
            out.write(struct.pack("<II", rel_offset, len(text_bytes)))
            out.seek(current)
    return output_path


def extract_text_csv(input_dir: Path, csv_path: Path) -> int:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with csv_path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out, delimiter=";")
        writer.writerow(
            ["Number", "File", "All Blocks", "Work Blocks", "HeaderData", "ID", "OriginalText"]
        )
        for dat_file in sorted(input_dir.glob("*.dat")):
            if dat_file.name.endswith("_0.dat"):
                continue
            doc = read_dat_document(dat_file)
            if doc is None:
                continue
            for idx, entry in enumerate(doc.entries):
                count += 1
                writer.writerow(
                    [
                        str(count),
                        doc.file_name,
                        doc.count_full,
                        doc.work_blocks,
                        doc.header_hex if idx == 0 else "",
                        entry.id_hex,
                        entry.text,
                    ]
                )
    return count


def load_csv_documents(csv_path: Path) -> dict[str, DatDocument]:
    docs: dict[str, DatDocument] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter=";")
        next(reader, None)
        for row in reader:
            if len(row) < 7:
                continue
            file_name = row[1]
            docs.setdefault(
                file_name,
                DatDocument(
                    file_name=file_name,
                    count_full=int(row[2]),
                    work_blocks=int(row[3]),
                    header_hex=row[4],
                    entries=[],
                ),
            )
            docs[file_name].entries.append(DatEntry(id_hex=row[5], text=row[6]))
            if row[4]:
                docs[file_name].header_hex = row[4]
    return docs


def _escape(text: str) -> str:
    return text.replace("\n", "\\n").replace("\r", "\\r")


def _unescape(text: str) -> str:
    return text.replace("\\n", "\n").replace("\\r", "\r")


def _table_offset(count_full: int) -> int:
    if count_full <= 8:
        return 48
    if count_full <= 128:
        return 56
    if count_full <= 256:
        return 296
    return 552


def _default_header(count_full: int, work_blocks_count: int) -> bytes:
    header = struct.pack("<II", work_blocks_count, 0)
    header += b"\xdc\x96\x58\x59\x00\x00\x00\x00"
    header += b"\x80" * count_full
    header += b"\xff"
    table_offset = 8 if count_full == 0 else ((count_full + 16) // 16 * 16) + 25
    padding = table_offset - 4 - len(header)
    if padding > 0:
        header += b"\x80" * padding
    return header
