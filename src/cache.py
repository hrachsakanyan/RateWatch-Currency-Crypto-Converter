"""Local rate cache and the freshness policy that decides when to hit the network.

The cache is a single JSON file holding one :class:`~src.models.RateSnapshot`.
Because the snapshot carries its own ``fetched_at`` timestamp, "is this stale?"
is answered locally and costs no network call.

The policy itself lives in :func:`resolve_snapshot`, which takes the fetcher as a
callable. That keeps this module free of any HTTP dependency and lets the tests
drive every branch — fresh hit, forced refresh, offline, stale fallback — with a
plain function.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import CACHE_FILENAME, DEFAULT_DATA_DIR, DEFAULT_MAX_AGE
from .errors import ApiError, CacheError, NoRatesAvailableError
from .models import RateSnapshot

# Outcomes reported by resolve_snapshot, so the CLI can explain what it did.
STATUS_FRESH = "fresh-cache"
STATUS_REFRESHED = "refreshed"
STATUS_STALE_OFFLINE = "stale-offline"
STATUS_STALE_FALLBACK = "stale-fallback"


class RatesCache:
    """Reads and writes the snapshot file, creating its directory on demand."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_DATA_DIR / CACHE_FILENAME

    # --- reading -------------------------------------------------------------

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> RateSnapshot | None:
        """Return the cached snapshot, or ``None`` when no cache file exists.

        A file that exists but cannot be parsed raises :class:`CacheError` —
        that is a real problem worth reporting, not a silent cache miss.
        """
        if not self.exists():
            return None
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CacheError(f"cannot read cache file {self.path}: {exc}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CacheError(f"cache file {self.path} is not valid JSON: {exc}") from exc
        return RateSnapshot.from_dict(payload)

    # --- writing -------------------------------------------------------------

    def save(self, snapshot: RateSnapshot) -> None:
        """Persist ``snapshot`` atomically.

        The JSON is written to a temporary file next to the target and then
        renamed over it, so an interrupted run can never leave a half-written
        cache behind for the next one to choke on.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(snapshot.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
        except OSError as exc:
            raise CacheError(f"cannot write cache file {self.path}: {exc}") from exc

    def clear(self) -> bool:
        """Delete the cache file. Returns True if a file was actually removed."""
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise CacheError(f"cannot delete cache file {self.path}: {exc}") from exc


@dataclass
class SnapshotResult:
    """A snapshot plus the story of where it came from."""

    snapshot: RateSnapshot
    status: str
    warnings: list[str] = field(default_factory=list)

    @property
    def is_stale(self) -> bool:
        return self.status in (STATUS_STALE_OFFLINE, STATUS_STALE_FALLBACK)


Fetcher = Callable[[], RateSnapshot]


def resolve_snapshot(
    cache: RatesCache,
    fetcher: Fetcher,
    max_age: float = DEFAULT_MAX_AGE,
    *,
    force_refresh: bool = False,
    offline: bool = False,
    allow_stale: bool = True,
) -> SnapshotResult:
    """Return usable rates, refreshing from the network only when necessary.

    The order of preference is:

    1. ``offline`` — use whatever is cached, however old, and never touch the network.
    2. A cached snapshot younger than ``max_age`` (unless ``force_refresh``).
    3. A fresh fetch, which is then written to the cache.
    4. If the fetch fails and ``allow_stale``, the stale cache with a warning.

    Raises :class:`NoRatesAvailableError` when none of those can be satisfied.
    """
    warnings: list[str] = []

    try:
        cached = cache.load()
    except CacheError as exc:
        # A corrupt cache should not be fatal: warn, then treat it as a miss.
        warnings.append(f"ignoring unreadable cache ({exc})")
        cached = None

    if offline:
        if cached is None:
            raise NoRatesAvailableError(
                "offline mode requested but no cached rates exist — "
                "run `ratewatch refresh` once while online"
            )
        status = STATUS_FRESH if cached.is_fresh(max_age) else STATUS_STALE_OFFLINE
        return SnapshotResult(cached, status, warnings)

    if cached is not None and not force_refresh and cached.is_fresh(max_age):
        return SnapshotResult(cached, STATUS_FRESH, warnings)

    try:
        snapshot = fetcher()
    except ApiError as exc:
        if cached is not None and allow_stale:
            warnings.append(f"could not refresh rates ({exc}); using cached rates")
            return SnapshotResult(cached, STATUS_STALE_FALLBACK, warnings)
        raise NoRatesAvailableError(
            f"could not fetch rates and no cached rates are available: {exc}"
        ) from exc

    try:
        cache.save(snapshot)
    except CacheError as exc:
        # The rates are good even if we failed to persist them.
        warnings.append(f"fetched rates but could not save cache ({exc})")

    return SnapshotResult(snapshot, STATUS_REFRESHED, warnings)
