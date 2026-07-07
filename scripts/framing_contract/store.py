from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from .model import FRAMING_CONTRACT_FILENAME, normalize_contract
except ImportError:
    from model import FRAMING_CONTRACT_FILENAME, normalize_contract


def contract_path(workspace: str | Path) -> Path:
    return Path(workspace) / FRAMING_CONTRACT_FILENAME


def load_contract(workspace: str | Path) -> dict[str, Any]:
    path = contract_path(workspace)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return normalize_contract(raw)


def save_contract(workspace: str | Path, contract: dict[str, Any]) -> Path:
    path = contract_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_contract(contract)
    payload = json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)
    return path
