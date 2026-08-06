"""HTTP client that assembles one rate snapshot from two free providers.

Fiat rates come from open.er-api.com and crypto spot prices from CoinGecko.
Neither needs an API key. Both are normalised onto the same base currency so the
rest of the program never has to care which provider a code came from.

Fiat is mandatory — without it there is no snapshot. Crypto and the currency-name
lookup are best effort: if CoinGecko rate-limits us (a plain HTTP 429 is common
on its free tier) RateWatch still returns a perfectly usable fiat snapshot and
records a warning instead of failing the whole run.
"""

from __future__ import annotations

from typing import Any

import requests

from .config import (
    BASE_CURRENCY,
    CRYPTO_COINS,
    CRYPTO_PRICE_URL,
    FIAT_NAMES_URL,
    FIAT_RATES_URL,
    KIND_CRYPTO,
    KIND_FIAT,
    REQUEST_TIMEOUT,
    USER_AGENT,
)
from .errors import ApiError
from .models import CurrencyInfo, RateSnapshot, utcnow


class RateApiClient:
    """Fetches and normalises rates from the configured providers."""

    def __init__(
        self,
        base: str = BASE_CURRENCY,
        *,
        timeout: float = REQUEST_TIMEOUT,
        session: requests.Session | None = None,
        coins: dict[str, tuple[str, str]] | None = None,
        include_crypto: bool = True,
    ) -> None:
        self.base = base.upper()
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.coins = CRYPTO_COINS if coins is None else coins
        self.include_crypto = include_crypto
        #: Non-fatal problems from the most recent fetch_snapshot() call.
        self.warnings: list[str] = []

    # --- public API ----------------------------------------------------------

    def fetch_snapshot(self) -> RateSnapshot:
        """Fetch everything and return a single normalised snapshot.

        Raises :class:`ApiError` only if the fiat rates could not be obtained.
        """
        self.warnings = []

        rates, sources = self._fetch_fiat()
        currencies = {
            code: CurrencyInfo(code=code, name=code, kind=KIND_FIAT) for code in rates
        }

        for code, name in self._fetch_fiat_names().items():
            if code in currencies:
                currencies[code] = CurrencyInfo(code=code, name=name, kind=KIND_FIAT)

        if self.include_crypto and self.coins:
            crypto_rates, crypto_names = self._fetch_crypto()
            for code, rate in crypto_rates.items():
                if code in rates:
                    # An ISO 4217 code always wins; skip the colliding ticker.
                    self.warnings.append(
                        f"skipped crypto ticker {code} — it collides with a fiat code"
                    )
                    continue
                rates[code] = rate
                currencies[code] = CurrencyInfo(
                    code=code, name=crypto_names[code], kind=KIND_CRYPTO
                )
            if crypto_rates:
                sources[KIND_CRYPTO] = CRYPTO_PRICE_URL

        return RateSnapshot(
            rates=rates,
            currencies=currencies,
            base=self.base,
            fetched_at=utcnow(),
            sources=sources,
        )

    # --- providers -----------------------------------------------------------

    def _fetch_fiat(self) -> tuple[dict[str, float], dict[str, str]]:
        """Fiat rates quoted per 1 unit of the base currency."""
        url = FIAT_RATES_URL.format(base=self.base)
        payload = self._get_json(url)

        if payload.get("result") != "success":
            detail = payload.get("error-type") or payload.get("result") or "unknown error"
            raise ApiError(f"fiat rate provider rejected the request: {detail}")

        raw = payload.get("rates")
        if not isinstance(raw, dict) or not raw:
            raise ApiError("fiat rate provider returned no rates")

        rates: dict[str, float] = {}
        for code, value in raw.items():
            try:
                rate = float(value)
            except (TypeError, ValueError):
                continue  # one bad row should not sink the whole response
            if rate > 0:
                rates[str(code).upper()] = rate

        if not rates:
            raise ApiError("fiat rate provider returned no usable rates")

        rates.setdefault(self.base, 1.0)
        sources = {KIND_FIAT: url}
        if payload.get("time_last_update_utc"):
            sources["fiat_published"] = str(payload["time_last_update_utc"])
        return rates, sources

    def _fetch_fiat_names(self) -> dict[str, str]:
        """ISO code -> display name. Purely cosmetic, so failures are swallowed."""
        try:
            payload = self._get_json(FIAT_NAMES_URL)
        except ApiError as exc:
            self.warnings.append(f"currency names unavailable ({exc}); showing codes only")
            return {}
        return {
            str(code).upper(): str(name)
            for code, name in payload.items()
            if isinstance(name, str)
        }

    def _fetch_crypto(self) -> tuple[dict[str, float], dict[str, str]]:
        """Crypto rates expressed the same way as fiat: coins per 1 base unit."""
        ids = {coin_id: symbol for symbol, (coin_id, _) in self.coins.items()}
        params = {
            "ids": ",".join(sorted(ids)),
            "vs_currencies": self.base.lower(),
        }
        try:
            payload = self._get_json(CRYPTO_PRICE_URL, params=params)
        except ApiError as exc:
            self.warnings.append(f"crypto rates unavailable ({exc}); fiat only")
            return {}, {}

        vs = self.base.lower()
        rates: dict[str, float] = {}
        names: dict[str, str] = {}
        for coin_id, quote in payload.items():
            symbol = ids.get(str(coin_id))
            if symbol is None or not isinstance(quote, dict):
                continue
            try:
                price = float(quote[vs])
            except (KeyError, TypeError, ValueError):
                continue
            if price <= 0:
                continue
            # The provider gives base-per-coin; we store coins-per-base like fiat.
            rates[symbol] = 1.0 / price
            names[symbol] = self.coins[symbol][1]

        missing = sorted(set(self.coins) - set(rates))
        if missing:
            self.warnings.append(f"no crypto price returned for: {', '.join(missing)}")
        return rates, names

    # --- transport -----------------------------------------------------------

    def _get_json(self, url: str, params: dict[str, str] | None = None) -> Any:
        """GET ``url`` and decode JSON, turning every failure into an ApiError."""
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.Timeout as exc:
            raise ApiError(f"{url} timed out after {self.timeout:g}s") from exc
        except requests.ConnectionError as exc:
            raise ApiError(f"cannot reach {url} — check your connection") from exc
        except requests.RequestException as exc:
            raise ApiError(f"request to {url} failed: {exc}") from exc

        if response.status_code == 429:
            raise ApiError(f"{url} rate-limited the request (HTTP 429), try again later")
        if response.status_code >= 400:
            raise ApiError(f"{url} returned HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiError(f"{url} returned a non-JSON response") from exc

        if not isinstance(payload, dict):
            raise ApiError(f"{url} returned unexpected JSON ({type(payload).__name__})")
        return payload
