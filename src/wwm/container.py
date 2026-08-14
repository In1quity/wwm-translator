from __future__ import annotations

import re
import struct
from pathlib import Path

import pyzstd

MAGIC = b"\xef\xbe\xad\xde"


def unpack_container(input_file: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    base_name = input_file.name

    with input_file.open("rb") as fh:
        if fh.read(4) != MAGIC:
            raise ValueError(f"Unsupported container magic: {input_file}")
        fh.read(4)  # version
        offset_count = struct.unpack("<I", fh.read(4))[0] + 1

        if offset_count == 1:
            comp_len = struct.unpack("<I", fh.read(4))[0]
            block = fh.read(comp_len)
            payload = _decompress_block(block)
            out = output_dir / f"{base_name}_0.dat"
            out.write_bytes(payload)
            written.append(out)
            return written

        offsets = [struct.unpack("<I", fh.read(4))[0] for _ in range(offset_count)]
        data_start = fh.tell()
        for i in range(offset_count - 1):
            current = offsets[i]
            nxt = offsets[i + 1]
            fh.seek(data_start + current)
            block = fh.read(nxt - current)
            if len(block) < 9:
                continue
            payload = _decompress_block(block)
            out = output_dir / f"{base_name}_{i}.dat"
            out.write_bytes(payload)
            written.append(out)
    return written


def pack_container(input_dir: Path, output_file: Path) -> Path:
    files = sorted(input_dir.glob("*.dat"), key=_extract_number)
    if not files:
        raise FileNotFoundError(f"No .dat files in {input_dir}")
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with output_file.open("wb") as out:
        out.write(MAGIC)
        out.write(b"\x01\x00\x00\x00")
        out.write(struct.pack("<I", len(files)))

        blocks: list[bytes] = []
        for file_path in files:
            data = file_path.read_bytes()
            comp = pyzstd.compress(data)
            blocks.append(struct.pack("<BII", 4, len(comp), len(data)) + comp)

        offsets = [0]
        total = 0
        for block in blocks:
            total += len(block)
            offsets.append(total)
        for value in offsets:
            out.write(struct.pack("<I", value))

        archive = b"".join(blocks)
        out.write(archive)
    return output_file


def _decompress_block(block: bytes) -> bytes:
    if len(block) < 9:
        return b""
    comp_type, _comp_size, _decomp_size = struct.unpack("<BII", block[:9])
    if comp_type != 4:
        return b""
    return pyzstd.decompress(block[9:])


def _extract_number(path: Path) -> int:
    match = re.search(r"_(\d+)\.dat$", path.name)
    return int(match.group(1)) if match else 10**9
