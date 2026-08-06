"""Tests for conversion arithmetic, currency lookup and money formatting."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.config import KIND_CRYPTO
from src.converter import (
    convert,
    format_amount,
    format_rate,
    get_rate,
    parse_amount,
    resolve_code,
    search_currencies,
)
from src.errors import RateWatchError, UnknownCurrencyError

# --- amount parsing ----------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("100", Decimal("100")),
        ("1,250.75", Decimal("1250.75")),
        ("0.5", Decimal("0.5")),
        ("  42  ", Decimal("42")),
        ("1_000", Decimal("1000")),
        ("-5", Decimal("-5")),
        ("1e3", Decimal("1000")),
    ],
)
def test_parse_amount_accepts_common_forms(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "12abc", "NaN", "Infinity", "  "])
def test_parse_amount_rejects_junk(text):
    with pytest.raises(RateWatchError):
        parse_amount(text)


def test_parse_amount_keeps_precision_that_float_would_lose():
    assert parse_amount("0.1") + parse_amount("0.2") == Decimal("0.3")


# --- code resolution ---------------------------------------------------------


def test_resolve_code_is_case_insensitive_and_trims(snapshot):
    assert resolve_code(snapshot, " eur ") == "EUR"
    assert resolve_code(snapshot, "btc") == "BTC"


def test_resolve_code_rejects_unknown_codes(snapshot):
    with pytest.raises(UnknownCurrencyError) as excinfo:
        resolve_code(snapshot, "ZZZ")
    assert excinfo.value.code == "ZZZ"


def test_unknown_code_suggests_a_near_miss(snapshot):
    with pytest.raises(UnknownCurrencyError) as excinfo:
        resolve_code(snapshot, "EUROS")
    assert "EUR" in excinfo.value.suggestions
    assert "did you mean" in str(excinfo.value)


def test_search_matches_code_or_name(snapshot):
    assert [i.code for i in search_currencies(snapshot, "bit")] == ["BTC"]
    assert [i.code for i in search_currencies(snapshot, "dram")] == ["AMD"]
    assert [i.code for i in search_currencies(snapshot, kind=KIND_CRYPTO)] == ["BTC", "ETH"]
    assert search_currencies(snapshot, "nothing-here") == []


# --- rates -------------------------------------------------------------------


def test_rate_from_the_base_currency_is_the_stored_rate(snapshot):
    assert get_rate(snapshot, "USD", "EUR") == Decimal("0.86")


def test_rate_to_the_base_currency_is_the_inverse(snapshot):
    assert get_rate(snapshot, "EUR", "USD") == pytest.approx(Decimal(1) / Decimal("0.86"))


def test_cross_rate_avoids_the_base_currency(snapshot):
    # EUR -> JPY should equal 150 / 0.86 without USD appearing in the result.
    assert get_rate(snapshot, "EUR", "JPY") == Decimal("150") / Decimal("0.86")


def test_identical_currencies_convert_one_to_one(snapshot):
    assert get_rate(snapshot, "EUR", "EUR") == Decimal(1)
    assert convert(snapshot, "123.45", "EUR", "EUR").result == Decimal("123.45")


def test_rate_and_its_inverse_multiply_back_to_one(snapshot):
    forward = get_rate(snapshot, "GBP", "BTC")
    backward = get_rate(snapshot, "BTC", "GBP")
    assert forward * backward == pytest.approx(Decimal(1))


def test_convert_reports_every_part_of_the_calculation(snapshot):
    result = convert(snapshot, "100", "usd", "eur")
    assert result.source == "USD"
    assert result.target == "EUR"
    assert result.amount == Decimal("100")
    assert result.rate == Decimal("0.86")
    assert result.result == Decimal("86.00")


def test_convert_crypto_to_fiat(snapshot):
    result = convert(snapshot, "1", "BTC", "USD")
    assert result.result == Decimal("62500")


def test_convert_fiat_to_crypto(snapshot):
    result = convert(snapshot, "1000", "USD", "BTC")
    assert result.result == Decimal("0.016")


def test_convert_crypto_to_crypto(snapshot):
    # 1 BTC (62,500 USD) at 2,000 USD per ETH == 31.25 ETH
    assert convert(snapshot, "1", "BTC", "ETH").result == Decimal("31.25")


def test_convert_rejects_an_unknown_currency(snapshot):
    with pytest.raises(UnknownCurrencyError):
        convert(snapshot, "10", "USD", "XYZ")


# --- formatting --------------------------------------------------------------


def test_ordinary_fiat_gets_two_decimals_and_separators(snapshot):
    assert format_amount(Decimal("1234567.891"), "EUR", snapshot) == "1,234,567.89 EUR"


def test_zero_decimal_currency_is_shown_without_decimals(snapshot):
    assert format_amount(Decimal("15000.4"), "JPY", snapshot) == "15,000 JPY"


def test_three_decimal_currency_keeps_three_decimals(snapshot):
    assert format_amount(Decimal("37.6789"), "BHD", snapshot) == "37.679 BHD"


def test_rounding_is_half_up_not_bankers(snapshot):
    # Python's round() would give 2.66 here; money conventions expect 2.68.
    assert format_amount(Decimal("2.675"), "USD", snapshot) == "2.68 USD"
    assert format_amount(Decimal("2.665"), "USD", snapshot) == "2.67 USD"


def test_crypto_keeps_small_fractions(snapshot):
    assert format_amount(Decimal("0.01600000"), "BTC", snapshot) == "0.016 BTC"
    # Eight decimals is one satoshi, so dust survives instead of rounding away.
    assert format_amount(Decimal("0.000000015"), "BTC", snapshot) == "0.00000002 BTC"


def test_crypto_below_one_satoshi_rounds_to_zero(snapshot):
    assert format_amount(Decimal("0.000000000001"), "BTC", snapshot) == "0.00 BTC"


def test_crypto_whole_numbers_keep_two_decimals(snapshot):
    assert format_amount(Decimal("2"), "BTC", snapshot) == "2.00 BTC"


def test_format_amount_can_omit_the_code(snapshot):
    assert format_amount(Decimal("5"), "USD", snapshot, with_code=False) == "5.00"


@pytest.mark.parametrize(
    "rate, expected",
    [
        (Decimal("0.86"), "0.86"),
        (Decimal("0.866698"), "0.866698"),
        (Decimal("150"), "150.00"),
        (Decimal("62500"), "62,500.00"),
        (Decimal("0.000016"), "0.000016"),
        (Decimal("0"), "0"),
    ],
)
def test_format_rate_scales_precision_to_magnitude(rate, expected):
    assert format_rate(rate) == expected
