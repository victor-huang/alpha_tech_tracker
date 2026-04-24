import json
import logging
import os
import threading
from datetime import date
from pathlib import Path
from typing import List, Optional

from .models import ActivePosition

logger = logging.getLogger(__name__)

STATE_DIR = Path(__file__).parent / "state"


def _state_path(session_date: date) -> Path:
    return STATE_DIR / f"session_{session_date}.json"


def save(
    positions: List[ActivePosition],
    session_date: date,
    metadata: Optional[dict] = None,
) -> None:
    """Write all positions (open + closed) to a dated checkpoint file.

    Uses a tmp-then-rename atomic write so readers never see a partial file.
    Swallows all exceptions — a failed checkpoint must never crash the engine.
    """
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        path = _state_path(session_date)
        data = {
            "date": str(session_date),
            "positions": [p.to_dict() for p in positions],
        }
        if metadata:
            data["metadata"] = metadata
        tmp = path.with_suffix(f".{os.getpid()}_{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(path)
    except Exception:
        logger.exception("session_state.save failed — checkpoint not written")


def load(session_date: date) -> List[ActivePosition]:
    """Read positions from today's checkpoint file.

    Returns an empty list when the file does not exist, belongs to a different
    date, or cannot be parsed — never raises.
    """
    path = _state_path(session_date)
    try:
        if not path.exists():
            return []
        data = json.loads(path.read_text())
        if data.get("date") != str(session_date):
            logger.warning(
                "session_state.load: file date %s != requested %s — ignoring",
                data.get("date"),
                session_date,
            )
            return []
        return [ActivePosition.from_dict(p) for p in data.get("positions", [])]
    except Exception:
        logger.exception("session_state.load failed — returning empty list")
        return []


def load_metadata(session_date: date) -> dict:
    """Read metadata from today's checkpoint file. Returns {} on any error."""
    path = _state_path(session_date)
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text())
        if data.get("date") != str(session_date):
            return {}
        return data.get("metadata", {})
    except Exception:
        logger.exception("session_state.load_metadata failed")
        return {}


def delete(session_date: date) -> None:
    """Delete the checkpoint file for the given date. Swallows all errors."""
    path = _state_path(session_date)
    try:
        path.unlink(missing_ok=True)
        logger.info("session_state.delete: removed checkpoint %s", path)
    except Exception:
        logger.exception("session_state.delete failed")
