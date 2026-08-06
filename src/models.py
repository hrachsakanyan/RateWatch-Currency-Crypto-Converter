"""The data model shared by the API client, the cache and the converter.

A :class:`RateSnapshot` is the single unit RateWatch works with: every rate it
holds is quoted against one base currency, captured at one moment in time. That
keeps conversion trivial (``rates[to] / rates[from]``) and makes freshness a
property of the whole snapshot rather than of individual pairs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import BASE_CURRENCY, KIND_CRYPTO, KIND_FIAT
from .errors import CacheError

#: Bumped whenever the on-disk layout changes; older files are then discarded.
SCHEMA_VERSION = 1


def utcnow() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class CurrencyInfo:
    """Display metadata for one currency code."""

    code: str
    name: str
    kind: str  # KIND_FIAT or KIND_CRYPTO

    @property
    def is_crypto(self) -> bool:
        return self.kind == KIND_CRYPTO


@dataclass(frozen=True)
class RateSnapshot:
    """A complete set of rates against ``base``, captured at ``fetched_at``."""

    rates: dict[str, float]
    currencies: dict[str, CurrencyInfo] = field(default_factory=dict)
    base: str = BASE_CURRENCY
    fetched_at: datetime = field(default_factory=utcnow)
    sources: dict[str, str] = field(default_factory=dict)

    # --- freshness -----------------------------------------------------------

    def age_seconds(self, now: datetime | None = None) -> float:
        """Seconds elapsed since this snapshot was fetched (never negative)."""
        now = now or utcnow()
        return max(0.0, (now - self.fetched_at).total_seconds())

    def is_fresh(self, max_age: float, now: datetime | None = None) -> bool:
        """True if the snapshot is younger than ``max_age`` seconds."""
        return self.age_seconds(now) < max_age

    # --- lookups -------------------------------------------------------------

    def has(self, code: str) -> bool:
        return code.upper() in self.rates

    def info(self, code: str) -> CurrencyInfo:
        """Metadata for ``code``, synthesised if the provider gave no name."""
        code = code.upper()
        return self.currencies.get(code, CurrencyInfo(code, code, KIND_FIAT))

    def codes(self, kind: str | None = None) -> list[str]:
        """Sorted currency codes, optionally filtered to ``fiat`` or ``crypto``."""
        codes = sorted(self.rates)
        if kind is None:
            return codes
        return [c for c in codes if self.info(c).kind == kind]

    def __len__(self) -> int:
        return len(self.rates)

    # --- serialisation -------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_VERSION,
            "base": self.base,
            "fetched_at": self.fetched_at.isoformat(),
            "sources": self.sources,
            "currencies": {
                code: {"name": info.name, "kind": info.kind}
                for code, info in self.currencies.items()
            },
            "rates": self.rates,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "RateSnapshot":
        """Rebuild a snapshot from its ``to_dict`` form.

        Raises :class:`CacheError` on anything malformed so callers can treat a
        damaged file the same way as a missing one.
        """
        if not isinstance(payload, dict):
            raise CacheError("cache root is not a JSON object")

        if payload.get("schema") != SCHEMA_VERSION:
            raise CacheError(
                f"cache schema {payload.get('schema')!r} is not supported "
                f"(expected {SCHEMA_VERSION})"
            )

        raw_rates = payload.get("rates")
        if not isinstance(raw_rates, dict) or not raw_rates:
            raise CacheError("cache contains no rates")

        try:
            rates = {str(code).upper(): float(value) for code, value in raw_rates.items()}
        except (TypeError, ValueError) as exc:
            raise CacheError(f"cache contains a non-numeric rate: {exc}") from exc

        try:
            fetched_at = datetime.fromisoformat(str(payload["fetched_at"]))
        except (KeyError, ValueError) as exc:
            raise CacheError(f"cache has an invalid 'fetched_at': {exc}") from exc
        if fetched_at.tzinfo is None:  # tolerate files written without an offset
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)

        currencies = {}
        for code, meta in (payload.get("currencies") or {}).items():
            if not isinstance(meta, dict):
                continue
            code = str(code).upper()
            kind = meta.get("kind", KIND_FIAT)
            currencies[code] = CurrencyInfo(
                code=code,
                name=str(meta.get("name") or code),
                kind=kind if kind in (KIND_FIAT, KIND_CRYPTO) else KIND_FIAT,
            )

        return cls(
            rates=rates,
            currencies=currencies,
            base=str(payload.get("base", BASE_CURRENCY)).upper(),
            fetched_at=fetched_at,
            sources=dict(payload.get("sources") or {}),
        )
