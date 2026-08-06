"""Tests for the API client, driven by a fake HTTP session (no network access).

The client's job is normalisation and graceful degradation, so most of these
tests are about what happens when a provider misbehaves.
"""

from __future__ import annotations

import pytest
import requests

from src.api_client import RateApiClient
from src.config import KIND_CRYPTO, KIND_FIAT
from src.errors import ApiError

FIAT_HOST = "open.er-api.com"
NAMES_HOST = "openexchangerates.org"
CRYPTO_HOST = "coingecko.com"

FIAT_OK = {
    "result": "success",
    "base_code": "USD",
    "time_last_update_utc": "Mon, 03 Aug 2026 00:02:32 +0000",
    "rates": {"USD": 1, "EUR": 0.86, "JPY": 150.0},
}
NAMES_OK = {"USD": "United States Dollar", "EUR": "Euro", "JPY": "Japanese Yen"}
CRYPTO_OK = {"bitcoin": {"usd": 62500}, "ethereum": {"usd": 2000}}

COINS = {"BTC": ("bitcoin", "Bitcoin"), "ETH": ("ethereum", "Ethereum")}


class FakeResponse:
    def __init__(self, payload=None, status_code=200, valid_json=True):
        self._payload = payload
        self.status_code = status_code
        self._valid_json = valid_json

    def json(self):
        if not self._valid_json:
            raise ValueError("no JSON could be decoded")
        return self._payload


class FakeSession:
    """Routes requests to canned responses by matching a substring of the URL."""

    def __init__(self, routes):
        self.headers = {}
        self.routes = routes
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        for fragment, response in self.routes.items():
            if fragment in url:
                if isinstance(response, Exception):
                    raise response
                return response
        raise AssertionError(f"unexpected request to {url}")


def make_client(routes, **kwargs):
    kwargs.setdefault("coins", COINS)
    return RateApiClient(session=FakeSession(routes), **kwargs)


def all_ok_routes():
    return {
        FIAT_HOST: FakeResponse(FIAT_OK),
        NAMES_HOST: FakeResponse(NAMES_OK),
        CRYPTO_HOST: FakeResponse(CRYPTO_OK),
    }


# --- the happy path ----------------------------------------------------------


def test_fetch_snapshot_merges_fiat_and_crypto():
    snapshot = make_client(all_ok_routes()).fetch_snapshot()

    assert snapshot.base == "USD"
    assert snapshot.rates["EUR"] == 0.86
    assert snapshot.codes(KIND_CRYPTO) == ["BTC", "ETH"]
    assert sorted(snapshot.codes(KIND_FIAT)) == ["EUR", "JPY", "USD"]


def test_crypto_prices_are_inverted_onto_the_base_currency():
    snapshot = make_client(all_ok_routes()).fetch_snapshot()
    # The provider quotes USD per BTC; we store BTC per USD.
    assert snapshot.rates["BTC"] == pytest.approx(1 / 62500)
    assert snapshot.rates["ETH"] == pytest.approx(1 / 2000)


def test_display_names_are_attached():
    snapshot = make_client(all_ok_routes()).fetch_snapshot()
    assert snapshot.info("EUR").name == "Euro"
    assert snapshot.info("BTC").name == "Bitcoin"
    assert snapshot.info("BTC").kind == KIND_CRYPTO


def test_publication_time_is_recorded_as_a_source():
    snapshot = make_client(all_ok_routes()).fetch_snapshot()
    assert snapshot.sources["fiat_published"] == FIAT_OK["time_last_update_utc"]


def test_the_base_currency_is_always_present():
    routes = all_ok_routes()
    routes[FIAT_HOST] = FakeResponse({**FIAT_OK, "rates": {"EUR": 0.86}})
    snapshot = make_client(routes).fetch_snapshot()
    assert snapshot.rates["USD"] == 1.0


def test_crypto_can_be_switched_off():
    client = make_client(all_ok_routes(), include_crypto=False)
    snapshot = client.fetch_snapshot()
    assert snapshot.codes(KIND_CRYPTO) == []
    assert not any(CRYPTO_HOST in url for url, _ in client.session.calls)


# --- degradation -------------------------------------------------------------


def test_a_rate_limited_crypto_provider_still_yields_fiat_rates():
    routes = all_ok_routes()
    routes[CRYPTO_HOST] = FakeResponse(status_code=429)
    client = make_client(routes)

    snapshot = client.fetch_snapshot()

    assert snapshot.rates["EUR"] == 0.86
    assert snapshot.codes(KIND_CRYPTO) == []
    assert any("crypto rates unavailable" in w for w in client.warnings)
    assert any("429" in w for w in client.warnings)


def test_missing_names_fall_back_to_codes():
    routes = all_ok_routes()
    routes[NAMES_HOST] = FakeResponse(status_code=500)
    client = make_client(routes)

    snapshot = client.fetch_snapshot()

    assert snapshot.info("EUR").name == "EUR"
    assert any("currency names unavailable" in w for w in client.warnings)


def test_a_coin_with_no_price_is_reported_but_not_fatal():
    routes = all_ok_routes()
    routes[CRYPTO_HOST] = FakeResponse({"bitcoin": {"usd": 62500}})
    client = make_client(routes)

    snapshot = client.fetch_snapshot()

    assert snapshot.codes(KIND_CRYPTO) == ["BTC"]
    assert any("ETH" in w for w in client.warnings)


def test_a_crypto_ticker_colliding_with_a_fiat_code_is_skipped():
    routes = all_ok_routes()
    routes[CRYPTO_HOST] = FakeResponse({"some-euro-token": {"usd": 4}})
    client = make_client(routes, coins={"EUR": ("some-euro-token", "Euro Token")})

    snapshot = client.fetch_snapshot()

    assert snapshot.rates["EUR"] == 0.86  # the fiat rate survived
    assert snapshot.info("EUR").kind == KIND_FIAT
    assert any("collides" in w for w in client.warnings)


def test_unusable_fiat_rows_are_dropped():
    routes = all_ok_routes()
    routes[FIAT_HOST] = FakeResponse(
        {**FIAT_OK, "rates": {"USD": 1, "EUR": "n/a", "GBP": 0, "JPY": 150.0}}
    )
    snapshot = make_client(routes).fetch_snapshot()
    assert "EUR" not in snapshot.rates
    assert "GBP" not in snapshot.rates
    assert snapshot.rates["JPY"] == 150.0


# --- fatal failures ----------------------------------------------------------


def test_a_provider_error_response_raises():
    routes = all_ok_routes()
    routes[FIAT_HOST] = FakeResponse({"result": "error", "error-type": "unsupported-code"})
    with pytest.raises(ApiError, match="unsupported-code"):
        make_client(routes).fetch_snapshot()


def test_an_empty_rate_table_raises():
    routes = all_ok_routes()
    routes[FIAT_HOST] = FakeResponse({"result": "success", "rates": {}})
    with pytest.raises(ApiError, match="no rates"):
        make_client(routes).fetch_snapshot()


def test_an_http_error_raises():
    routes = all_ok_routes()
    routes[FIAT_HOST] = FakeResponse(status_code=503)
    with pytest.raises(ApiError, match="HTTP 503"):
        make_client(routes).fetch_snapshot()


def test_a_timeout_raises_a_readable_error():
    routes = all_ok_routes()
    routes[FIAT_HOST] = requests.Timeout("too slow")
    with pytest.raises(ApiError, match="timed out"):
        make_client(routes).fetch_snapshot()


def test_a_connection_failure_raises_a_readable_error():
    routes = all_ok_routes()
    routes[FIAT_HOST] = requests.ConnectionError("dns failure")
    with pytest.raises(ApiError, match="check your connection"):
        make_client(routes).fetch_snapshot()


def test_a_non_json_response_raises():
    routes = all_ok_routes()
    routes[FIAT_HOST] = FakeResponse(valid_json=False)
    with pytest.raises(ApiError, match="non-JSON"):
        make_client(routes).fetch_snapshot()


def test_unexpected_json_shape_raises():
    routes = all_ok_routes()
    routes[FIAT_HOST] = FakeResponse(["not", "an", "object"])
    with pytest.raises(ApiError, match="unexpected JSON"):
        make_client(routes).fetch_snapshot()
