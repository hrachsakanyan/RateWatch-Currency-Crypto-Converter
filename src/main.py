"""RateWatch command line interface.

Every subcommand that needs rates goes through :func:`load_rates`, which applies
the cache-freshness policy once and reports how the rates were obtained, so the
output can always tell you whether you are looking at fresh or cached numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import __version__
from .api_client import RateApiClient
from .cache import RatesCache, SnapshotResult, resolve_snapshot
from .config import (
    CACHE_FILENAME,
    DEFAULT_DATA_DIR,
    DEFAULT_MAX_AGE,
    HISTORY_FILENAME,
    KIND_CRYPTO,
    KIND_FIAT,
)
from .converter import (
    Conversion,
    convert,
    format_amount,
    format_rate,
    get_rate,
    resolve_code,
    search_currencies,
)
from .errors import RateWatchError
from .history import clear_history, log_conversion, read_history
from .models import RateSnapshot, utcnow

PROGRAM = "ratewatch"

EXIT_OK = 0
EXIT_ERROR = 1


@dataclass
class Context:
    """Resolved runtime paths for one CLI invocation."""

    cache: RatesCache
    history_path: Path

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "Context":
        data_dir = Path(args.data_dir) if args.data_dir else DEFAULT_DATA_DIR
        return cls(
            cache=RatesCache(data_dir / CACHE_FILENAME),
            history_path=data_dir / HISTORY_FILENAME,
        )


# --- rate loading ------------------------------------------------------------


def load_rates(args: argparse.Namespace, ctx: Context) -> SnapshotResult:
    """Get a snapshot using the cache policy implied by the CLI flags."""
    if args.offline and args.refresh:
        raise RateWatchError("--offline and --refresh cannot be used together")

    client = RateApiClient()
    result = resolve_snapshot(
        ctx.cache,
        client.fetch_snapshot,
        max_age=args.max_age,
        force_refresh=args.refresh,
        offline=args.offline,
    )
    result.warnings.extend(client.warnings)
    return result


# --- presentation helpers ----------------------------------------------------


def humanize_age(seconds: float) -> str:
    """A short, readable age such as '12 minutes' or '2 days'."""
    seconds = max(0.0, seconds)
    if seconds < 45:
        return "just now"
    for limit, size, unit in (
        (3600, 60, "minute"),
        (86400, 3600, "hour"),
        (2592000, 86400, "day"),
    ):
        if seconds < limit:
            value = int(round(seconds / size))
            return f"{value} {unit}{'s' if value != 1 else ''}"
    value = int(seconds // 2592000)
    return f"{value} month{'s' if value != 1 else ''}"


def describe_source(result: SnapshotResult) -> str:
    """One line explaining where the rates came from and how old they are."""
    snapshot = result.snapshot
    age = humanize_age(snapshot.age_seconds())
    stamp = snapshot.fetched_at.strftime("%Y-%m-%d %H:%M UTC")
    if result.status == "refreshed":
        return f"fetched live from the API ({stamp})"
    origin = "cache, offline mode" if result.status == "stale-offline" else "cache"
    label = "STALE " if result.is_stale else ""
    age_phrase = age if age == "just now" else f"{age} old"
    return f"{label}{origin}, {age_phrase} (fetched {stamp})"


def snapshot_meta(result: SnapshotResult) -> dict:
    """The rate-source block shared by every --json payload."""
    snapshot = result.snapshot
    return {
        "status": result.status,
        "stale": result.is_stale,
        "base": snapshot.base,
        "fetched_at": snapshot.fetched_at.isoformat(),
        "age_seconds": round(snapshot.age_seconds(), 1),
        "currencies": len(snapshot),
        "sources": snapshot.sources,
    }


def emit_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def report_warnings(result: SnapshotResult) -> None:
    for message in result.warnings:
        warn(message)


def format_logged(value: object, code: object) -> str:
    """Format a value read back from the query log.

    The log deliberately stores unrounded Decimals, so display rounding happens
    here. No snapshot is loaded for `history`, hence the metadata-free variant.
    Anything unparsable is echoed as-is rather than hidden.
    """
    if value is None or code is None:
        return f"{value} {code}"
    try:
        return format_amount(Decimal(str(value)), str(code))
    except (InvalidOperation, ValueError):
        return f"{value} {code}"


def conversion_payload(conversion: Conversion, snapshot: RateSnapshot) -> dict:
    """JSON-safe view of a conversion, with Decimals rendered as strings."""
    return {
        "amount": str(conversion.amount),
        "from": conversion.source,
        "to": conversion.target,
        "rate": str(conversion.rate),
        "result": str(conversion.result),
        "formatted": {
            "amount": format_amount(conversion.amount, conversion.source, snapshot),
            "result": format_amount(conversion.result, conversion.target, snapshot),
            "rate": format_rate(conversion.rate),
        },
    }


# --- commands ----------------------------------------------------------------


def cmd_convert(args: argparse.Namespace, ctx: Context) -> int:
    result = load_rates(args, ctx)
    snapshot = result.snapshot
    conversion = convert(snapshot, args.amount, args.source, args.target)

    if not args.no_log:
        log_conversion(conversion, path=ctx.history_path, status=result.status)

    if args.as_json:
        report_warnings(result)
        emit_json(
            {
                **conversion_payload(conversion, snapshot),
                "rates": snapshot_meta(result),
                "warnings": result.warnings,
            }
        )
        return EXIT_OK

    report_warnings(result)
    inverse = Decimal(1) / conversion.rate if conversion.rate else Decimal(0)
    print()
    print(
        f"  {format_amount(conversion.amount, conversion.source, snapshot)}"
        f"  ->  {format_amount(conversion.result, conversion.target, snapshot)}"
    )
    print()
    print(f"  Rate      1 {conversion.source} = {format_rate(conversion.rate)} {conversion.target}")
    print(f"  Inverse   1 {conversion.target} = {format_rate(inverse)} {conversion.source}")
    print(f"  Rates     {describe_source(result)}")
    print()
    return EXIT_OK


def cmd_rate(args: argparse.Namespace, ctx: Context) -> int:
    result = load_rates(args, ctx)
    snapshot = result.snapshot
    source = resolve_code(snapshot, args.source)
    target = resolve_code(snapshot, args.target)
    rate = get_rate(snapshot, source, target)

    if args.as_json:
        report_warnings(result)
        emit_json(
            {
                "from": source,
                "to": target,
                "rate": str(rate),
                "formatted": format_rate(rate),
                "rates": snapshot_meta(result),
                "warnings": result.warnings,
            }
        )
        return EXIT_OK

    report_warnings(result)
    print(f"1 {source} = {format_rate(rate)} {target}")
    print(f"Rates: {describe_source(result)}")
    return EXIT_OK


def cmd_list(args: argparse.Namespace, ctx: Context) -> int:
    result = load_rates(args, ctx)
    snapshot = result.snapshot
    kind = None if args.kind == "all" else args.kind
    matches = search_currencies(snapshot, args.search, kind)

    if args.as_json:
        report_warnings(result)
        emit_json(
            {
                "currencies": [
                    {
                        "code": info.code,
                        "name": info.name,
                        "kind": info.kind,
                        "rate_per_base": snapshot.rates[info.code],
                    }
                    for info in matches
                ],
                "count": len(matches),
                "rates": snapshot_meta(result),
                "warnings": result.warnings,
            }
        )
        return EXIT_OK

    report_warnings(result)
    if not matches:
        print(f"No currencies match {args.search!r}.")
        return EXIT_OK

    width = max(len("CODE"), *(len(info.code) for info in matches))
    print(f"{'CODE':<{width}}  {'KIND':<6}  NAME")
    for info in matches:
        print(f"{info.code:<{width}}  {info.kind:<6}  {info.name}")

    fiat = sum(1 for info in matches if info.kind == KIND_FIAT)
    crypto = sum(1 for info in matches if info.kind == KIND_CRYPTO)
    noun = "currency" if len(matches) == 1 else "currencies"
    print()
    print(f"{len(matches)} {noun} ({fiat} fiat, {crypto} crypto) — base {snapshot.base}")
    print(f"Rates: {describe_source(result)}")
    return EXIT_OK


def cmd_refresh(args: argparse.Namespace, ctx: Context) -> int:
    args.refresh = True
    args.offline = False
    result = load_rates(args, ctx)
    snapshot = result.snapshot

    if args.as_json:
        report_warnings(result)
        emit_json({"rates": snapshot_meta(result), "warnings": result.warnings})
        return EXIT_OK

    report_warnings(result)
    fiat = len(snapshot.codes(KIND_FIAT))
    crypto = len(snapshot.codes(KIND_CRYPTO))
    print(f"Refreshed {len(snapshot)} rates ({fiat} fiat, {crypto} crypto) against {snapshot.base}.")
    print(f"Cache: {ctx.cache.path}")
    print(f"Source: {describe_source(result)}")
    return EXIT_OK


def cmd_cache(args: argparse.Namespace, ctx: Context) -> int:
    if args.clear:
        removed = ctx.cache.clear()
        print("Cache cleared." if removed else "No cache file to clear.")
        return EXIT_OK

    path = ctx.cache.path
    if not ctx.cache.exists():
        if args.as_json:
            emit_json({"path": str(path), "exists": False})
            return EXIT_OK
        print(f"No cache yet at {path}")
        print("Run `ratewatch refresh` to create it.")
        return EXIT_OK

    snapshot = ctx.cache.load()
    assert snapshot is not None  # exists() was true, load() only returns None if absent
    age = snapshot.age_seconds()
    fresh = snapshot.is_fresh(args.max_age)

    if args.as_json:
        emit_json(
            {
                "path": str(path),
                "exists": True,
                "fresh": fresh,
                "max_age_seconds": args.max_age,
                "age_seconds": round(age, 1),
                "fetched_at": snapshot.fetched_at.isoformat(),
                "base": snapshot.base,
                "currencies": len(snapshot),
                "size_bytes": path.stat().st_size,
                "sources": snapshot.sources,
            }
        )
        return EXIT_OK

    print(f"Cache file   {path}")
    print(f"Size         {path.stat().st_size:,} bytes")
    print(f"Fetched      {snapshot.fetched_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Age          {humanize_age(age)} ({age:.0f}s)")
    print(f"Freshness    {'fresh' if fresh else 'STALE'} (max age {args.max_age:.0f}s)")
    print(f"Base         {snapshot.base}")
    print(
        f"Currencies   {len(snapshot)} "
        f"({len(snapshot.codes(KIND_FIAT))} fiat, {len(snapshot.codes(KIND_CRYPTO))} crypto)"
    )
    for name, value in snapshot.sources.items():
        print(f"  {name:<16} {value}")
    return EXIT_OK


def parse_batch_line(line: str) -> tuple[str, str, str] | None:
    """Parse one batch line into ``(amount, from, to)``.

    Accepts whitespace- or comma-separated fields. Blank lines and lines
    starting with ``#`` return ``None`` so callers can skip them.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    fields = [part for part in stripped.replace(",", " ").split() if part]
    if len(fields) != 3:
        raise RateWatchError(
            f"expected 'AMOUNT FROM TO' but got {len(fields)} field(s): {stripped!r}"
        )
    amount, source, target = fields
    return amount, source, target


def cmd_batch(args: argparse.Namespace, ctx: Context) -> int:
    path = Path(args.file)
    try:
        # utf-8-sig, not utf-8: Notepad, Excel and PowerShell's Out-File all
        # prepend a BOM, which would otherwise glue itself to the first field.
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise RateWatchError(f"cannot read batch file {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise RateWatchError(f"batch file {path} is not valid UTF-8 text: {exc}") from exc

    result = load_rates(args, ctx)
    snapshot = result.snapshot
    report_warnings(result)

    rows: list[dict] = []
    failures = 0
    for number, line in enumerate(lines, start=1):
        try:
            parsed = parse_batch_line(line)
            if parsed is None:
                continue
            amount, source, target = parsed
            conversion = convert(snapshot, amount, source, target)
        except RateWatchError as exc:
            failures += 1
            rows.append({"line": number, "error": str(exc), "input": line.strip()})
            continue
        if not args.no_log:
            log_conversion(conversion, path=ctx.history_path, status=result.status)
        rows.append({"line": number, **conversion_payload(conversion, snapshot)})

    if args.as_json:
        emit_json(
            {
                "file": str(path),
                "conversions": rows,
                "converted": len(rows) - failures,
                "failed": failures,
                "rates": snapshot_meta(result),
                "warnings": result.warnings,
            }
        )
        return EXIT_ERROR if failures else EXIT_OK

    if not rows:
        print(f"{path} contained no conversions.")
        return EXIT_OK

    for row in rows:
        if "error" in row:
            print(f"  line {row['line']}: error — {row['error']}")
        else:
            print(
                f"  {row['formatted']['amount']:>22}  ->  {row['formatted']['result']:<22}"
                f"  @ {row['formatted']['rate']}"
            )
    print()
    print(f"{len(rows) - failures} converted, {failures} failed — {describe_source(result)}")
    return EXIT_ERROR if failures else EXIT_OK


def cmd_history(args: argparse.Namespace, ctx: Context) -> int:
    if args.clear:
        removed = clear_history(ctx.history_path)
        print("History cleared." if removed else "No history file to clear.")
        return EXIT_OK

    entries = read_history(args.limit, path=ctx.history_path)
    if args.as_json:
        emit_json({"entries": entries, "count": len(entries)})
        return EXIT_OK

    if not entries:
        print("No conversions logged yet.")
        return EXIT_OK

    rows = []
    for entry in entries:
        when = str(entry.get("at", "")).replace("T", " ")[:19]
        summary = (
            f"{format_logged(entry.get('amount'), entry.get('from'))}"
            f" -> {format_logged(entry.get('result'), entry.get('to'))}"
        )
        rows.append((when, summary, str(entry.get("rates_status", ""))))

    width = max(len("CONVERSION"), *(len(summary) for _, summary, _ in rows))
    print(f"{'WHEN':<20} {'CONVERSION':<{width}} RATES")
    for when, summary, status in rows:
        print(f"{when:<20} {summary:<{width}} {status}")
    print()
    print(f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} from {ctx.history_path}")
    return EXIT_OK


# --- argument parsing --------------------------------------------------------


def add_common_flags(parser: argparse.ArgumentParser, *, suppress: bool) -> None:
    """Add the shared rate-source flags.

    They are defined twice — once on the top level parser with real defaults and
    once on each subparser. The subparser copies use ``SUPPRESS`` as the default
    so that omitting a flag after the subcommand does not overwrite a value the
    user gave before it. That makes both ``ratewatch --offline convert ...`` and
    ``ratewatch convert ... --offline`` work.
    """

    def default(value):
        return argparse.SUPPRESS if suppress else value

    group = parser.add_argument_group("rate source options")
    group.add_argument(
        "--max-age",
        type=float,
        metavar="SECONDS",
        default=default(float(DEFAULT_MAX_AGE)),
        help=f"how old cached rates may be before refetching (default: {DEFAULT_MAX_AGE})",
    )
    group.add_argument(
        "-r",
        "--refresh",
        action="store_true",
        default=default(False),
        help="ignore cache age and fetch from the API",
    )
    group.add_argument(
        "--offline",
        action="store_true",
        default=default(False),
        help="never touch the network; use cached rates at any age",
    )
    group.add_argument(
        "--data-dir",
        metavar="PATH",
        default=default(None),
        help=f"where the cache and log live (default: {DEFAULT_DATA_DIR})",
    )
    group.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        default=default(False),
        help="print machine-readable JSON instead of a formatted report",
    )
    group.add_argument(
        "--no-log",
        action="store_true",
        default=default(False),
        help="do not record this conversion in the query log",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Convert between currencies and crypto using cached live rates.",
        epilog=(
            "examples:\n"
            f"  {PROGRAM} convert 100 USD EUR\n"
            f"  {PROGRAM} convert 0.5 BTC AMD\n"
            f"  {PROGRAM} rate EUR JPY --refresh\n"
            f"  {PROGRAM} list --kind crypto\n"
            f"  {PROGRAM} convert 20 USD GBP --offline\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    add_common_flags(parser, suppress=False)

    common = argparse.ArgumentParser(add_help=False)
    add_common_flags(common, suppress=True)

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    convert_parser = subparsers.add_parser(
        "convert", parents=[common], help="convert an amount between two currencies"
    )
    convert_parser.add_argument("amount", help="amount to convert, e.g. 100 or 1,250.75")
    convert_parser.add_argument("source", metavar="FROM", help="currency to convert from")
    convert_parser.add_argument("target", metavar="TO", help="currency to convert to")
    convert_parser.set_defaults(func=cmd_convert)

    rate_parser = subparsers.add_parser(
        "rate", parents=[common], help="show the exchange rate for one pair"
    )
    rate_parser.add_argument("source", metavar="FROM", help="base currency")
    rate_parser.add_argument("target", metavar="TO", help="quote currency")
    rate_parser.set_defaults(func=cmd_rate)

    list_parser = subparsers.add_parser(
        "list", parents=[common], help="list supported currencies"
    )
    list_parser.add_argument(
        "--kind",
        choices=["all", KIND_FIAT, KIND_CRYPTO],
        default="all",
        help="restrict the listing to fiat or crypto (default: all)",
    )
    list_parser.add_argument(
        "--search", metavar="TEXT", help="only show codes or names containing TEXT"
    )
    list_parser.set_defaults(func=cmd_list)

    refresh_parser = subparsers.add_parser(
        "refresh", parents=[common], help="force a fetch and rewrite the cache"
    )
    refresh_parser.set_defaults(func=cmd_refresh)

    cache_parser = subparsers.add_parser(
        "cache", parents=[common], help="show or clear the local rate cache"
    )
    cache_parser.add_argument(
        "--clear", action="store_true", help="delete the cache file"
    )
    cache_parser.set_defaults(func=cmd_cache)

    batch_parser = subparsers.add_parser(
        "batch",
        parents=[common],
        help="convert every 'AMOUNT FROM TO' line in a file",
    )
    batch_parser.add_argument("file", help="path to the batch file")
    batch_parser.set_defaults(func=cmd_batch)

    history_parser = subparsers.add_parser(
        "history", parents=[common], help="show previously logged conversions"
    )
    history_parser.add_argument(
        "-n", "--limit", type=int, default=10, help="how many entries to show (default: 10)"
    )
    history_parser.add_argument(
        "--clear", action="store_true", help="delete the query log"
    )
    history_parser.set_defaults(func=cmd_history)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Currency names contain accented characters; a legacy console codepage
    # should degrade them, not crash the program.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except (ValueError, OSError):  # pragma: no cover - depends on the terminal
            pass

    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_OK

    try:
        return args.func(args, Context.from_args(args))
    except RateWatchError as exc:
        print(f"{PROGRAM}: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("\nInterrupted.", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
