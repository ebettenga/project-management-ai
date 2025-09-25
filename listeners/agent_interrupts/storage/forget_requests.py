"""Persistence helpers for forget command approvals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


FORGET_STORE = Path("data/forget_requests")


def _ensure_dir() -> None:
    FORGET_STORE.mkdir(parents=True, exist_ok=True)


def save_request(request_id: str, payload: Dict[str, Any]) -> None:
    _ensure_dir()
    with open(FORGET_STORE / f"{request_id}.json", "w", encoding="utf-8") as file:
        json.dump(payload, file)


def load_request(request_id: str) -> Optional[Dict[str, Any]]:
    filepath = FORGET_STORE / f"{request_id}.json"
    if not filepath.exists():
        return None

    with open(filepath, "r", encoding="utf-8") as file:
        try:
            return json.load(file)
        except json.JSONDecodeError:
            return None


def delete_request(request_id: str) -> None:
    filepath = FORGET_STORE / f"{request_id}.json"
    if filepath.exists():
        filepath.unlink()
