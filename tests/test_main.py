"""End-to-end CLI tests.

The cache is pre-seeded and ``--offline`` is used almost everywhere, so the
whole command surface is exercised without a single network call.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from src import main as cli
from src.cache import RatesCache
from src.main import build_parser, humanize_age, main, parse_batch_line

from conftest import make_snapshot


@pytest.fixture
def seeded(data_dir, snapshot):
    """A data directory containing a fresh cache."""
    RatesCache(data_dir / "rates_cache.json").save(snapshot)
    return data_dir


@pytest.fixture
def seeded_stale(data_dir, stale_snapshot):
    RatesCache(data_dir / "rates_cache.json").save(stale_snapshot)
    return data_dir


def run(argv, data_dir):
    return main([*argv, "--data-dir", str(data_dir)])


# --- convert -----------------------------------------------------------------


def test_convert_prints_the_result(seeded, capsys):
    assert run(["convert", "100", "USD", "EUR", "--offline"], seeded) == 0
    out = capsys.readouterr().out
    assert "100.00 USD" in out
    assert "86.00 EUR" in out
    assert "1 USD = 0.86 EUR" in out
    assert "Inverse" in out


def test_a_just_fetched_cache_reads_naturally(seeded, capsys):
    run(["convert", "1", "USD", "EUR", "--offline"], seeded)
    out = capsys.readouterr().out
    assert "cache, just now (fetched" in out
    assert "just now old" not in out


def test_convert_is_case_insensitive(seeded, capsys):
    assert run(["convert", "100", "usd", "eur", "--offline"], seeded) == 0
    assert "86.00 EUR" in capsys.readouterr().out


def test_convert_crypto(seeded, capsys):
    assert run(["convert", "0.5", "BTC", "USD", "--offline"], seeded) == 0
    assert "31,250.00 USD" in capsys.readouterr().out


def test_convert_json_output_is_machine_readable(seeded, capsys):
    assert run(["convert", "100", "USD", "JPY", "--offline", "--json"], seeded) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["from"] == "USD"
    assert payload["to"] == "JPY"
    # The raw value is unrounded; `formatted` carries the display form.
    assert Decimal(payload["result"]) == Decimal("15000")
    assert payload["formatted"]["result"] == "15,000 JPY"
    assert payload["rates"]["status"] == "fresh-cache"
    assert payload["rates"]["stale"] is False


def test_flags_are_accepted_before_the_subcommand(seeded, capsys):
    assert main(["--offline", "--data-dir", str(seeded), "convert", "1", "USD", "EUR"]) == 0
    assert "0.86 EUR" in capsys.readouterr().out


def test_unknown_currency_exits_with_an_error(seeded, capsys):
    assert run(["convert", "10", "USD", "ZZZ", "--offline"], seeded) == 1
    assert "unknown currency" in capsys.readouterr().err


def test_a_typo_gets_a_suggestion(seeded, capsys):
    assert run(["convert", "10", "USD", "EURO", "--offline"], seeded) == 1
    assert "did you mean" in capsys.readouterr().err


def test_an_invalid_amount_exits_with_an_error(seeded, capsys):
    assert run(["convert", "abc", "USD", "EUR", "--offline"], seeded) == 1
    assert "invalid amount" in capsys.readouterr().err


def test_offline_and_refresh_are_mutually_exclusive(seeded, capsys):
    assert run(["convert", "1", "USD", "EUR", "--offline", "--refresh"], seeded) == 1
    assert "cannot be used together" in capsys.readouterr().err


def test_offline_without_a_cache_explains_what_to_do(data_dir, capsys):
    assert run(["convert", "1", "USD", "EUR", "--offline"], data_dir) == 1
    assert "ratewatch refresh" in capsys.readouterr().err


def test_stale_rates_are_flagged_in_the_output(seeded_stale, capsys):
    assert run(["convert", "1", "USD", "EUR", "--offline"], seeded_stale) == 0
    assert "STALE" in capsys.readouterr().out


# --- rate / list / cache -----------------------------------------------------


def test_rate_prints_a_single_line(seeded, capsys):
    assert run(["rate", "USD", "EUR", "--offline"], seeded) == 0
    assert capsys.readouterr().out.splitlines()[0] == "1 USD = 0.86 EUR"


def test_list_shows_every_currency(seeded, capsys):
    assert run(["list", "--offline"], seeded) == 0
    out = capsys.readouterr().out
    assert "Bitcoin" in out and "Euro" in out
    assert "8 currencies (6 fiat, 2 crypto)" in out


def test_list_can_be_filtered_by_kind(seeded, capsys):
    assert run(["list", "--kind", "crypto", "--offline"], seeded) == 0
    out = capsys.readouterr().out
    assert "BTC" in out and "EUR" not in out


def test_list_can_be_searched(seeded, capsys):
    assert run(["list", "--search", "dram", "--offline"], seeded) == 0
    out = capsys.readouterr().out
    assert "AMD" in out
    assert "1 currency (" in out  # singular, not "1 currencies"


def test_list_columns_line_up_with_short_codes(seeded, capsys):
    run(["list", "--search", "dram", "--offline"], seeded)
    lines = capsys.readouterr().out.splitlines()
    header, row = lines[0], lines[1]
    assert header.index("KIND") == row.index("fiat")


def test_list_reports_an_empty_search_politely(seeded, capsys):
    assert run(["list", "--search", "zzzz", "--offline"], seeded) == 0
    assert "No currencies match" in capsys.readouterr().out


def test_cache_status_reports_freshness(seeded, capsys):
    assert run(["cache"], seeded) == 0
    out = capsys.readouterr().out
    assert "fresh" in out
    assert "Currencies   8" in out


def test_cache_status_without_a_cache(data_dir, capsys):
    assert run(["cache"], data_dir) == 0
    assert "No cache yet" in capsys.readouterr().out


def test_cache_clear_removes_the_file(seeded, capsys):
    assert run(["cache", "--clear"], seeded) == 0
    assert "Cache cleared" in capsys.readouterr().out
    assert not (seeded / "rates_cache.json").exists()


def test_cache_json_reports_staleness(seeded_stale, capsys):
    assert run(["cache", "--json"], seeded_stale) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["exists"] is True
    assert payload["fresh"] is False


# --- refresh (with a stubbed client) -----------------------------------------


class StubClient:
    """Stands in for RateApiClient so `refresh` can be tested offline."""

    def __init__(self, *args, **kwargs):
        self.warnings = ["crypto rates unavailable (stub); fiat only"]

    def fetch_snapshot(self):
        return make_snapshot()


def test_refresh_fetches_and_writes_the_cache(data_dir, monkeypatch, capsys):
    monkeypatch.setattr(cli, "RateApiClient", StubClient)
    assert run(["refresh"], data_dir) == 0

    captured = capsys.readouterr()
    assert "Refreshed 8 rates" in captured.out
    assert "crypto rates unavailable" in captured.err  # client warnings surface
    assert (data_dir / "rates_cache.json").is_file()


def test_a_failed_refresh_falls_back_to_the_cache(seeded_stale, monkeypatch, capsys):
    from src.errors import ApiError

    class BrokenClient(StubClient):
        def fetch_snapshot(self):
            raise ApiError("network down")

    monkeypatch.setattr(cli, "RateApiClient", BrokenClient)
    assert run(["convert", "1", "USD", "EUR", "--refresh"], seeded_stale) == 0

    captured = capsys.readouterr()
    assert "network down" in captured.err
    assert "STALE" in captured.out
    assert "0.86 EUR" in captured.out


# --- batch -------------------------------------------------------------------


@pytest.mark.parametrize(
    "line, expected",
    [
        ("100 USD EUR", ("100", "USD", "EUR")),
        ("  0.5   btc   usd  ", ("0.5", "btc", "usd")),
        ("100,USD,EUR", ("100", "USD", "EUR")),
        ("", None),
        ("   ", None),
        ("# a comment", None),
    ],
)
def test_parse_batch_line(line, expected):
    assert parse_batch_line(line) == expected


@pytest.mark.parametrize("line", ["100 USD", "100 USD EUR GBP", "justonefield"])
def test_parse_batch_line_rejects_the_wrong_field_count(line):
    from src.errors import RateWatchError

    with pytest.raises(RateWatchError, match="expected 'AMOUNT FROM TO'"):
        parse_batch_line(line)


def test_batch_converts_every_line(seeded, tmp_path, capsys):
    batch = tmp_path / "batch.txt"
    batch.write_text(
        "# quarterly invoices\n100 USD EUR\n\n0.5 BTC USD\n2000,JPY,USD\n",
        encoding="utf-8",
    )

    assert run(["batch", str(batch), "--offline"], seeded) == 0
    out = capsys.readouterr().out
    assert "86.00 EUR" in out
    assert "31,250.00 USD" in out
    assert "3 converted, 0 failed" in out


def test_batch_reports_bad_lines_without_aborting(seeded, tmp_path, capsys):
    batch = tmp_path / "batch.txt"
    batch.write_text("100 USD EUR\nnonsense\n5 USD ZZZ\n50 USD GBP\n", encoding="utf-8")

    assert run(["batch", str(batch), "--offline"], seeded) == 1
    out = capsys.readouterr().out
    assert "1 converted" not in out
    assert "2 converted, 2 failed" in out
    assert "line 2: error" in out
    assert "unknown currency" in out


def test_batch_tolerates_a_utf8_bom(seeded, tmp_path, capsys):
    # Notepad and PowerShell's Out-File -Encoding utf8 both write a BOM.
    batch = tmp_path / "bom.txt"
    batch.write_text("# invoices\n100 USD EUR\n", encoding="utf-8-sig")

    assert run(["batch", str(batch), "--offline"], seeded) == 0
    out = capsys.readouterr().out
    assert "86.00 EUR" in out
    assert "1 converted, 0 failed" in out


def test_batch_on_a_missing_file_errors(seeded, tmp_path, capsys):
    assert run(["batch", str(tmp_path / "nope.txt"), "--offline"], seeded) == 1
    assert "cannot read batch file" in capsys.readouterr().err


# --- history -----------------------------------------------------------------


def test_conversions_are_logged_and_listed(seeded, capsys):
    run(["convert", "100", "USD", "EUR", "--offline"], seeded)
    run(["convert", "1", "BTC", "USD", "--offline"], seeded)
    capsys.readouterr()  # discard the conversion output

    assert run(["history"], seeded) == 0
    out = capsys.readouterr().out
    assert "USD -> 86.00 EUR" in out
    assert "2 entries" in out


def test_no_log_skips_the_history(seeded, capsys):
    run(["convert", "100", "USD", "EUR", "--offline", "--no-log"], seeded)
    capsys.readouterr()

    assert run(["history"], seeded) == 0
    assert "No conversions logged yet" in capsys.readouterr().out


def test_history_can_be_limited_and_cleared(seeded, capsys):
    for amount in ("1", "2", "3"):
        run(["convert", amount, "USD", "EUR", "--offline"], seeded)
    capsys.readouterr()

    run(["history", "-n", "2"], seeded)
    assert "2 entries" in capsys.readouterr().out

    assert run(["history", "--clear"], seeded) == 0
    assert "History cleared" in capsys.readouterr().out


# --- parser plumbing ---------------------------------------------------------


def test_no_command_prints_help(capsys):
    assert main([]) == 0
    assert "usage:" in capsys.readouterr().out


def test_version_flag_exits_cleanly(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0


def test_an_unknown_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        main(["frobnicate"])
    assert excinfo.value.code == 2


def test_every_subcommand_accepts_the_shared_flags():
    parser = build_parser()
    for command in ("convert", "rate", "list", "refresh", "cache", "batch", "history"):
        assert command in parser.format_help()


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, "just now"),
        (44, "just now"),
        (120, "2 minutes"),
        (60, "1 minute"),
        (7200, "2 hours"),
        (172800, "2 days"),
        (5184000, "2 months"),
    ],
)
def test_humanize_age(seconds, expected):
    assert humanize_age(seconds) == expected
