import json
from pathlib import Path
from typing import Any, Dict, Optional

APPROVAL_STORE = Path("data/approval_requests")


def _ensure_dir() -> None:
    APPROVAL_STORE.mkdir(parents=True, exist_ok=True)


def save_request(interrupt_id: str, payload: Dict[str, Any]) -> None:
    _ensure_dir()
    with open(APPROVAL_STORE / f"{interrupt_id}.json", "w", encoding="utf-8") as file:
        json.dump(payload, file)


def load_request(interrupt_id: str) -> Optional[Dict[str, Any]]:
    filepath = APPROVAL_STORE / f"{interrupt_id}.json"
    if not filepath.exists():
        return None

    with open(filepath, "r", encoding="utf-8") as file:
        try:
            return json.load(file)
        except json.JSONDecodeError:
            return None


def delete_request(interrupt_id: str) -> None:
    filepath = APPROVAL_STORE / f"{interrupt_id}.json"
    if filepath.exists():
        filepath.unlink()
