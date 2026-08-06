"""Append-only log of past conversions.

Stored as JSON Lines so appending is a single write with no read-modify-write of
the whole file, and a truncated or hand-edited line only costs that one entry.

Logging is a convenience, never a precondition: :func:`log_conversion` swallows
its own errors so a read-only data directory can't break a conversion.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import DEFAULT_DATA_DIR, HISTORY_FILENAME
from .converter import Conversion
from .models import utcnow


def default_path() -> Path:
    return DEFAULT_DATA_DIR / HISTORY_FILENAME


def log_conversion(
    conversion: Conversion,
    *,
    path: str | Path | None = None,
    status: str = "",
) -> bool:
    """Append one conversion to the log. Returns False if it could not be written."""
    entry = {
        "at": utcnow().isoformat(timespec="seconds"),
        "amount": str(conversion.amount),
        "from": conversion.source,
        "to": conversion.target,
        "rate": str(conversion.rate),
        "result": str(conversion.result),
        "rates_status": status,
    }
    target = Path(path) if path else default_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        return True
    except OSError:
        return False


def read_history(limit: int = 10, *, path: str | Path | None = None) -> list[dict]:
    """Return the most recent entries, newest last. Unparsable lines are skipped."""
    target = Path(path) if path else default_path()
    if not target.is_file():
        return []
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    entries: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)

    if limit is not None and limit > 0:
        return entries[-limit:]
    return entries


def clear_history(path: str | Path | None = None) -> bool:
    """Delete the log file. Returns True if a file was actually removed."""
    target = Path(path) if path else default_path()
    try:
        target.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
