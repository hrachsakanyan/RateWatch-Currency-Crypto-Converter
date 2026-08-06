"""Shared pytest fixtures.

The tests never touch the network: every fixture builds snapshots in memory or
feeds the API client a fake HTTP session.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

# Allow `import src...` when pytest is run from anywhere in the project.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import KIND_CRYPTO, KIND_FIAT  # noqa: E402
from src.models import CurrencyInfo, RateSnapshot, utcnow  # noqa: E402


def make_snapshot(age_seconds: float = 0.0) -> RateSnapshot:
    """A small but representative snapshot: 2/3/0-decimal fiat plus crypto."""
    rates = {
        "USD": 1.0,
        "EUR": 0.86,
        "GBP": 0.75,
        "JPY": 150.0,      # zero-decimal currency
        "BHD": 0.376,      # three-decimal currency
        "AMD": 383.0,
        "BTC": 0.000016,   # 1 BTC == 62,500 USD
        "ETH": 0.0005,     # 1 ETH == 2,000 USD
    }
    names = {
        "USD": ("United States Dollar", KIND_FIAT),
        "EUR": ("Euro", KIND_FIAT),
        "GBP": ("British Pound Sterling", KIND_FIAT),
        "JPY": ("Japanese Yen", KIND_FIAT),
        "BHD": ("Bahraini Dinar", KIND_FIAT),
        "AMD": ("Armenian Dram", KIND_FIAT),
        "BTC": ("Bitcoin", KIND_CRYPTO),
        "ETH": ("Ethereum", KIND_CRYPTO),
    }
    return RateSnapshot(
        rates=rates,
        currencies={
            code: CurrencyInfo(code, name, kind) for code, (name, kind) in names.items()
        },
        base="USD",
        fetched_at=utcnow() - timedelta(seconds=age_seconds),
        sources={"fiat": "https://example.test/fiat", "crypto": "https://example.test/crypto"},
    )


@pytest.fixture
def snapshot() -> RateSnapshot:
    """A freshly fetched snapshot."""
    return make_snapshot()


@pytest.fixture
def stale_snapshot() -> RateSnapshot:
    """A snapshot fetched five hours ago."""
    return make_snapshot(age_seconds=5 * 3600)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """An isolated data directory, so tests never write to the real one."""
    target = tmp_path / "data"
    target.mkdir()
    return target
