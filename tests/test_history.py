"""Tests for the JSON Lines query log."""

from __future__ import annotations

from decimal import Decimal

from src.converter import convert
from src.history import clear_history, log_conversion, read_history


def log_one(snapshot, path, amount="100", source="USD", target="EUR"):
    conversion = convert(snapshot, amount, source, target)
    return log_conversion(conversion, path=path, status="fresh-cache")


def test_reading_a_missing_log_returns_nothing(tmp_path):
    assert read_history(path=tmp_path / "absent.jsonl") == []


def test_a_logged_conversion_can_be_read_back(snapshot, tmp_path):
    path = tmp_path / "log.jsonl"
    assert log_one(snapshot, path) is True

    entries = read_history(path=path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["from"] == "USD"
    assert entry["to"] == "EUR"
    assert Decimal(entry["result"]) == Decimal("86.00")
    assert entry["rates_status"] == "fresh-cache"
    assert entry["at"].endswith("+00:00")


def test_entries_append_and_the_limit_keeps_the_newest(snapshot, tmp_path):
    path = tmp_path / "log.jsonl"
    for amount in ("1", "2", "3", "4", "5"):
        log_one(snapshot, path, amount=amount)

    assert len(read_history(limit=100, path=path)) == 5
    recent = read_history(limit=2, path=path)
    assert [e["amount"] for e in recent] == ["4", "5"]


def test_the_log_directory_is_created_on_demand(snapshot, tmp_path):
    path = tmp_path / "made" / "up" / "log.jsonl"
    assert log_one(snapshot, path) is True
    assert path.is_file()


def test_a_damaged_line_does_not_hide_the_others(snapshot, tmp_path):
    path = tmp_path / "log.jsonl"
    log_one(snapshot, path, amount="1")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{ truncated line\n\n")
    log_one(snapshot, path, amount="2")

    entries = read_history(path=path)
    assert [e["amount"] for e in entries] == ["1", "2"]


def test_logging_failure_is_reported_rather_than_raised(snapshot, tmp_path):
    # A file where a directory is expected makes the write impossible.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    assert log_one(snapshot, blocker / "log.jsonl") is False


def test_clear_reports_whether_it_removed_anything(snapshot, tmp_path):
    path = tmp_path / "log.jsonl"
    assert clear_history(path) is False
    log_one(snapshot, path)
    assert clear_history(path) is True
    assert read_history(path=path) == []
