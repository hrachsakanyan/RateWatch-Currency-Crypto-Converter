"""Tests for the cache file and, more importantly, the freshness policy."""

from __future__ import annotations

import pytest

from src.cache import (
    STATUS_FRESH,
    STATUS_REFRESHED,
    STATUS_STALE_FALLBACK,
    STATUS_STALE_OFFLINE,
    RatesCache,
    resolve_snapshot,
)
from src.errors import ApiError, CacheError, NoRatesAvailableError

from conftest import make_snapshot


@pytest.fixture
def cache(data_dir):
    return RatesCache(data_dir / "rates_cache.json")


def fetcher_returning(snapshot):
    """A fetcher that succeeds and counts how often it was called."""

    def fetch():
        fetch.calls += 1
        return snapshot

    fetch.calls = 0
    return fetch


def failing_fetcher(message="network down"):
    def fetch():
        fetch.calls += 1
        raise ApiError(message)

    fetch.calls = 0
    return fetch


# --- file handling -----------------------------------------------------------


def test_load_returns_none_when_no_cache_exists(cache):
    assert not cache.exists()
    assert cache.load() is None


def test_save_then_load_roundtrips(cache, snapshot):
    cache.save(snapshot)
    assert cache.exists()
    restored = cache.load()
    assert restored.rates == snapshot.rates
    assert restored.fetched_at == snapshot.fetched_at


def test_save_leaves_no_temporary_file_behind(cache, snapshot, data_dir):
    cache.save(snapshot)
    assert [p.name for p in data_dir.iterdir()] == ["rates_cache.json"]


def test_save_creates_a_missing_directory(tmp_path, snapshot):
    cache = RatesCache(tmp_path / "nested" / "deeper" / "rates.json")
    cache.save(snapshot)
    assert cache.load() is not None


def test_save_overwrites_an_existing_cache(cache, snapshot, stale_snapshot):
    cache.save(stale_snapshot)
    cache.save(snapshot)
    assert cache.load().fetched_at == snapshot.fetched_at


def test_load_raises_on_corrupt_json(cache):
    cache.path.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(CacheError, match="not valid JSON"):
        cache.load()


def test_clear_reports_whether_it_removed_anything(cache, snapshot):
    assert cache.clear() is False
    cache.save(snapshot)
    assert cache.clear() is True
    assert not cache.exists()


# --- freshness policy --------------------------------------------------------


def test_fresh_cache_is_used_without_fetching(cache, snapshot):
    cache.save(snapshot)
    fetch = fetcher_returning(snapshot)
    result = resolve_snapshot(cache, fetch, max_age=3600)
    assert result.status == STATUS_FRESH
    assert not result.is_stale
    assert fetch.calls == 0


def test_stale_cache_triggers_a_fetch_and_is_rewritten(cache, stale_snapshot):
    cache.save(stale_snapshot)
    fresh = make_snapshot()
    fetch = fetcher_returning(fresh)

    result = resolve_snapshot(cache, fetch, max_age=3600)

    assert result.status == STATUS_REFRESHED
    assert fetch.calls == 1
    assert cache.load().fetched_at == fresh.fetched_at


def test_missing_cache_triggers_a_fetch(cache, snapshot):
    fetch = fetcher_returning(snapshot)
    result = resolve_snapshot(cache, fetch, max_age=3600)
    assert result.status == STATUS_REFRESHED
    assert fetch.calls == 1
    assert cache.exists()


def test_force_refresh_ignores_a_fresh_cache(cache, snapshot):
    cache.save(snapshot)
    fetch = fetcher_returning(make_snapshot())
    result = resolve_snapshot(cache, fetch, max_age=3600, force_refresh=True)
    assert result.status == STATUS_REFRESHED
    assert fetch.calls == 1


def test_max_age_zero_always_refetches(cache, snapshot):
    cache.save(snapshot)
    fetch = fetcher_returning(snapshot)
    result = resolve_snapshot(cache, fetch, max_age=0)
    assert result.status == STATUS_REFRESHED
    assert fetch.calls == 1


def test_offline_uses_a_stale_cache_without_fetching(cache, stale_snapshot):
    cache.save(stale_snapshot)
    fetch = fetcher_returning(make_snapshot())
    result = resolve_snapshot(cache, fetch, max_age=3600, offline=True)
    assert result.status == STATUS_STALE_OFFLINE
    assert result.is_stale
    assert fetch.calls == 0


def test_offline_with_a_fresh_cache_is_not_flagged_stale(cache, snapshot):
    cache.save(snapshot)
    result = resolve_snapshot(cache, failing_fetcher(), max_age=3600, offline=True)
    assert result.status == STATUS_FRESH
    assert not result.is_stale


def test_offline_without_a_cache_raises(cache):
    with pytest.raises(NoRatesAvailableError, match="offline"):
        resolve_snapshot(cache, failing_fetcher(), offline=True)


def test_api_failure_falls_back_to_the_stale_cache_with_a_warning(cache, stale_snapshot):
    cache.save(stale_snapshot)
    result = resolve_snapshot(cache, failing_fetcher("no route to host"), max_age=3600)

    assert result.status == STATUS_STALE_FALLBACK
    assert result.is_stale
    assert result.snapshot.fetched_at == stale_snapshot.fetched_at
    assert any("no route to host" in w for w in result.warnings)


def test_api_failure_without_a_cache_raises(cache):
    with pytest.raises(NoRatesAvailableError, match="no cached rates"):
        resolve_snapshot(cache, failing_fetcher(), max_age=3600)


def test_api_failure_raises_when_stale_fallback_is_disabled(cache, stale_snapshot):
    cache.save(stale_snapshot)
    with pytest.raises(NoRatesAvailableError):
        resolve_snapshot(cache, failing_fetcher(), max_age=3600, allow_stale=False)


def test_a_corrupt_cache_is_reported_but_not_fatal(cache, snapshot):
    cache.path.write_text("not json at all", encoding="utf-8")
    result = resolve_snapshot(cache, fetcher_returning(snapshot), max_age=3600)
    assert result.status == STATUS_REFRESHED
    assert any("unreadable cache" in w for w in result.warnings)
    assert cache.load() is not None  # the good snapshot replaced the broken file
