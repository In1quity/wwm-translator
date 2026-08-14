from __future__ import annotations

import json
from pathlib import Path

PATCH_VERSION_PATH = Path("Package/HD/oversea/locale/patch_version.json")


def detect_client_version(game_root: Path) -> str:
    path = game_root / PATCH_VERSION_PATH
    if not path.is_file():
        raise FileNotFoundError(f"Missing patch version file: {path}")
    raw = path.read_text(encoding="utf-8").strip()
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                for key in ("version", "patch_version", "build"):
                    value = str(payload.get(key, "")).strip()
                    if value:
                        return value
        except json.JSONDecodeError:
            pass
    return raw

