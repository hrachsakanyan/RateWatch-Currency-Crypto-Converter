"""Tests for the RateSnapshot model: freshness maths and serialisation."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.config import KIND_CRYPTO, KIND_FIAT
from src.errors import CacheError
from src.models import SCHEMA_VERSION, RateSnapshot, utcnow


def test_fresh_snapshot_is_fresh(snapshot):
    assert snapshot.is_fresh(3600)
    assert snapshot.age_seconds() < 5


def test_stale_snapshot_is_not_fresh(stale_snapshot):
    assert not stale_snapshot.is_fresh(3600)
    assert stale_snapshot.age_seconds() == pytest.approx(5 * 3600, abs=5)


def test_age_never_goes_negative_for_a_future_timestamp():
    future = RateSnapshot(rates={"USD": 1.0}, fetched_at=utcnow() + timedelta(hours=1))
    assert future.age_seconds() == 0.0


def test_codes_can_be_filtered_by_kind(snapshot):
    assert snapshot.codes(KIND_CRYPTO) == ["BTC", "ETH"]
    assert "EUR" in snapshot.codes(KIND_FIAT)
    assert len(snapshot.codes()) == len(snapshot) == 8


def test_info_falls_back_to_the_code_when_metadata_is_missing():
    bare = RateSnapshot(rates={"USD": 1.0, "XYZ": 2.0})
    info = bare.info("XYZ")
    assert (info.code, info.name, info.kind) == ("XYZ", "XYZ", KIND_FIAT)


def test_roundtrip_preserves_rates_metadata_and_timestamp(snapshot):
    restored = RateSnapshot.from_dict(snapshot.to_dict())
    assert restored.rates == snapshot.rates
    assert restored.base == snapshot.base
    assert restored.fetched_at == snapshot.fetched_at
    assert restored.sources == snapshot.sources
    assert restored.info("BTC").name == "Bitcoin"
    assert restored.info("BTC").is_crypto


def test_from_dict_rejects_an_unknown_schema(snapshot):
    payload = snapshot.to_dict()
    payload["schema"] = SCHEMA_VERSION + 99
    with pytest.raises(CacheError, match="schema"):
        RateSnapshot.from_dict(payload)


def test_from_dict_rejects_empty_rates(snapshot):
    payload = snapshot.to_dict()
    payload["rates"] = {}
    with pytest.raises(CacheError, match="no rates"):
        RateSnapshot.from_dict(payload)


def test_from_dict_rejects_a_non_numeric_rate(snapshot):
    payload = snapshot.to_dict()
    payload["rates"]["EUR"] = "not-a-number"
    with pytest.raises(CacheError, match="non-numeric"):
        RateSnapshot.from_dict(payload)


def test_from_dict_rejects_a_broken_timestamp(snapshot):
    payload = snapshot.to_dict()
    payload["fetched_at"] = "yesterday"
    with pytest.raises(CacheError, match="fetched_at"):
        RateSnapshot.from_dict(payload)


def test_from_dict_assumes_utc_for_a_naive_timestamp(snapshot):
    payload = snapshot.to_dict()
    payload["fetched_at"] = "2026-01-01T00:00:00"
    restored = RateSnapshot.from_dict(payload)
    assert restored.fetched_at.tzinfo is not None
    assert restored.fetched_at.utcoffset().total_seconds() == 0
