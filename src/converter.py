"""Currency lookup, conversion arithmetic and money formatting.

Rates arrive from JSON as floats, but money should not be rounded with binary
floats. Every rate is therefore lifted into :class:`~decimal.Decimal` via its
string form before any arithmetic happens, and results are quantised with
``ROUND_HALF_UP`` — the rule people actually expect when handling cash — at the
number of decimals the target currency really uses.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from decimal import Decimal, DecimalException, InvalidOperation, ROUND_HALF_UP

from .config import (
    CRYPTO_COINS,
    CRYPTO_DECIMALS,
    FIAT_DECIMALS,
    KIND_CRYPTO,
    KIND_FIAT,
    THREE_DECIMAL_CURRENCIES,
    ZERO_DECIMAL_CURRENCIES,
)
from .errors import RateWatchError, UnknownCurrencyError
from .models import CurrencyInfo, RateSnapshot

#: Crypto amounts keep at least this many decimals even when they end in zeros,
#: so "2.00 BTC" does not collapse to a bare "2".
MIN_CRYPTO_DECIMALS = 2


@dataclass(frozen=True)
class Conversion:
    """The full result of one conversion, kept at unrounded precision."""

    amount: Decimal
    source: str
    target: str
    rate: Decimal
    result: Decimal


# --- currency lookup ---------------------------------------------------------


def resolve_code(snapshot: RateSnapshot, code: str) -> str:
    """Normalise ``code`` to a code present in ``snapshot``.

    Raises :class:`UnknownCurrencyError` with near-miss suggestions otherwise.
    """
    normalised = str(code).strip().upper()
    if not normalised:
        raise UnknownCurrencyError(code)
    if normalised in snapshot.rates:
        return normalised
    raise UnknownCurrencyError(normalised, suggest_codes(snapshot, normalised))


def suggest_codes(snapshot: RateSnapshot, code: str, limit: int = 3) -> list[str]:
    """Codes that look like a typo of ``code``, or whose name contains it."""
    suggestions = difflib.get_close_matches(code, list(snapshot.rates), n=limit, cutoff=0.6)
    if len(suggestions) < limit:
        needle = code.lower()
        for candidate in snapshot.codes():
            if len(suggestions) >= limit:
                break
            if candidate in suggestions:
                continue
            if needle in snapshot.info(candidate).name.lower():
                suggestions.append(candidate)
    return suggestions


def search_currencies(
    snapshot: RateSnapshot, query: str | None = None, kind: str | None = None
) -> list[CurrencyInfo]:
    """Currencies matching ``query`` (code or name substring), sorted by code."""
    results = [snapshot.info(code) for code in snapshot.codes(kind)]
    if query:
        needle = query.strip().lower()
        results = [
            info
            for info in results
            if needle in info.code.lower() or needle in info.name.lower()
        ]
    return results


# --- arithmetic --------------------------------------------------------------


def parse_amount(text: str | float | Decimal) -> Decimal:
    """Parse a user-supplied amount, tolerating thousands separators."""
    if isinstance(text, Decimal):
        candidate = text
    else:
        cleaned = str(text).strip().replace(",", "").replace("_", "")
        if not cleaned:
            raise RateWatchError("amount is empty")
        try:
            candidate = Decimal(cleaned)
        except (InvalidOperation, ValueError, DecimalException) as exc:
            raise RateWatchError(f"invalid amount {text!r} — expected a number") from exc
    if not candidate.is_finite():
        raise RateWatchError(f"invalid amount {text!r} — must be a finite number")
    return candidate


def get_rate(snapshot: RateSnapshot, source: str, target: str) -> Decimal:
    """How many units of ``target`` one unit of ``source`` buys.

    Both legs are quoted against the snapshot's base currency, so the cross rate
    is simply ``rates[target] / rates[source]``.
    """
    source = resolve_code(snapshot, source)
    target = resolve_code(snapshot, target)
    if source == target:
        return Decimal(1)

    source_rate = Decimal(str(snapshot.rates[source]))
    target_rate = Decimal(str(snapshot.rates[target]))
    if source_rate <= 0:
        raise RateWatchError(f"cached rate for {source} is not usable ({source_rate})")
    return target_rate / source_rate


def convert(
    snapshot: RateSnapshot, amount: str | float | Decimal, source: str, target: str
) -> Conversion:
    """Convert ``amount`` from ``source`` to ``target`` using ``snapshot``."""
    value = parse_amount(amount)
    source = resolve_code(snapshot, source)
    target = resolve_code(snapshot, target)
    rate = get_rate(snapshot, source, target)
    return Conversion(
        amount=value,
        source=source,
        target=target,
        rate=rate,
        result=value * rate,
    )


# --- formatting --------------------------------------------------------------


def decimals_for(info: CurrencyInfo) -> int:
    """How many decimal places ``info``'s currency is conventionally shown with."""
    if info.is_crypto:
        return CRYPTO_DECIMALS
    if info.code in ZERO_DECIMAL_CURRENCIES:
        return 0
    if info.code in THREE_DECIMAL_CURRENCIES:
        return 3
    return FIAT_DECIMALS


def quantize(value: Decimal, places: int) -> Decimal:
    """Round ``value`` to ``places`` decimals, half-up."""
    exponent = Decimal(1).scaleb(-places)
    return value.quantize(exponent, rounding=ROUND_HALF_UP)


def currency_info(code: str, snapshot: RateSnapshot | None = None) -> CurrencyInfo:
    """Metadata for ``code``, preferring the snapshot's own labels.

    Without a snapshot — reading back the query log, say — the kind is inferred
    from the shipped crypto table, which is enough to format the number.
    """
    code = str(code).upper()
    if snapshot is not None:
        return snapshot.info(code)
    kind = KIND_CRYPTO if code in CRYPTO_COINS else KIND_FIAT
    return CurrencyInfo(code, code, kind)


def format_amount(
    value: Decimal,
    code: str,
    snapshot: RateSnapshot | None = None,
    with_code: bool = True,
) -> str:
    """Render ``value`` the way that currency is normally written."""
    info = currency_info(code, snapshot)
    places = decimals_for(info)
    text = f"{quantize(value, places):,.{places}f}"
    if info.is_crypto:
        text = _strip_trailing_zeros(text, MIN_CRYPTO_DECIMALS)
    return f"{text} {info.code}" if with_code else text


def format_rate(rate: Decimal) -> str:
    """Render an exchange rate with enough precision to stay meaningful.

    Rates span many orders of magnitude — roughly 0.87 for USD/EUR but 0.000016
    for USD/BTC — so the decimal count is derived from the magnitude rather than
    fixed, targeting about six significant digits.
    """
    if not rate.is_finite() or rate == 0:
        return "0"
    places = max(2, min(12, 5 - abs(rate).adjusted()))
    return _strip_trailing_zeros(f"{quantize(rate, places):,.{places}f}", 2)


def _strip_trailing_zeros(text: str, min_decimals: int) -> str:
    """Trim trailing zeros from a decimal string, keeping ``min_decimals``."""
    if "." not in text:
        return text
    whole, fraction = text.split(".")
    fraction = fraction.rstrip("0")
    if len(fraction) < min_decimals:
        fraction = fraction.ljust(min_decimals, "0")
    return f"{whole}.{fraction}" if fraction else whole
