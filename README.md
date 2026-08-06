# RateWatch — Currency & Crypto Converter

A command line converter for fiat currencies and cryptocurrencies that caches
exchange rates locally, checks how old they are before using them, and keeps
working when the network does not.

Roughly **196 currencies** in one snapshot: ~166 ISO 4217 fiat currencies plus
30 major cryptocurrencies, all quoted against a single base so any pair can be
derived without another request.

```
$ python ratewatch.py convert 100 USD EUR

  100.00 USD  ->  86.67 EUR

  Rate      1 USD = 0.866698 EUR
  Inverse   1 EUR = 1.1538 USD
  Rates     cache, 3 minutes old (fetched 2026-08-03 08:56 UTC)
```

---

## Features

- **Convert anything to anything** — fiat↔fiat, fiat↔crypto, crypto↔crypto.
- **Local rate cache with a freshness check** — the network is only touched when
  the cached rates are older than `--max-age` (default: 1 hour).
- **Offline mode** — `--offline` works entirely from the cache, at any age.
- **Automatic stale fallback** — if a refresh fails, the last good rates are used
  and clearly labelled `STALE` rather than the command dying.
- **Money-correct arithmetic** — `Decimal` throughout, `ROUND_HALF_UP`, and the
  right number of decimals per currency (¥ has none, BHD has three, BTC has 8).
- **Currency listing and search** — by code, by name, filtered to fiat or crypto.
- **Batch conversions** from a file.
- **Query log** of everything you have converted.
- **`--json` on every command** for scripting.
- **Graceful degradation** — if the crypto provider rate-limits you, the fiat
  rates still come through with a warning.

## Requirements

- Python 3.9+
- `requests`

```bash
pip install -r requirements.txt
```

No API key is needed — every provider used here is free and unauthenticated.

## Quick start

```bash
python ratewatch.py refresh                # fetch rates and build the cache
python ratewatch.py convert 100 USD EUR
python ratewatch.py convert 0.5 BTC AMD
python ratewatch.py list --kind crypto
```

`python -m src.main ...` does exactly the same thing if you prefer running the
package directly. On Windows use the `py` launcher: `py ratewatch.py ...`.

---

## Commands

### `convert AMOUNT FROM TO`

```
$ python ratewatch.py convert 0.5 BTC AMD

  0.50 BTC  ->  11,426,516.18 AMD

  Rate      1 BTC = 22,853,032.36 AMD
  Inverse   1 AMD = 0.000000043758 BTC
  Rates     cache, just now (fetched 2026-08-03 08:56 UTC)
```

Amounts may contain thousands separators (`1,250.75`) and codes are
case-insensitive. A typo gets a suggestion instead of a bare failure:

```
$ python ratewatch.py convert 10 USD EURO
ratewatch: error: unknown currency code 'EURO' (did you mean: EUR?)
```

### `rate FROM TO`

One line, for piping into other tools.

```
$ python ratewatch.py rate EUR JPY
1 EUR = 182.319 JPY
Rates: cache, 3 minutes old (fetched 2026-08-03 08:56 UTC)
```

### `list [--kind fiat|crypto|all] [--search TEXT]`

```
$ python ratewatch.py list --search dram
CODE  KIND    NAME
AMD   fiat    Armenian Dram

1 currency (1 fiat, 0 crypto) — base USD
Rates: cache, 3 minutes old (fetched 2026-08-03 08:56 UTC)
```

`--search` matches both codes and names, so `--search bit` finds `BTC Bitcoin`.

### `refresh`

Forces a fetch and rewrites the cache, whatever its age.

```
$ python ratewatch.py refresh
Refreshed 196 rates (166 fiat, 30 crypto) against USD.
Cache: /path/to/ratewatch/data/rates_cache.json
Source: fetched live from the API (2026-08-03 08:56 UTC)
```

### `cache [--clear]`

Inspect the cache without fetching anything.

```
$ python ratewatch.py cache
Cache file   /path/to/ratewatch/data/rates_cache.json
Size         20,273 bytes
Fetched      2026-08-03 08:56:22 UTC
Age          just now (31s)
Freshness    fresh (max age 3600s)
Base         USD
Currencies   196 (166 fiat, 30 crypto)
  crypto           https://api.coingecko.com/api/v3/simple/price
  fiat             https://open.er-api.com/v6/latest/USD
  fiat_published   Mon, 03 Aug 2026 00:02:32 +0000
```

### `batch FILE`

One conversion per line, `AMOUNT FROM TO`, separated by spaces or commas. Blank
lines and `#` comments are ignored. A bad line is reported and the rest still
run; the exit code is `1` if anything failed.

```
# Q3 supplier invoices
1200 USD EUR
850,GBP,USD
0.25 BTC USD
2500 JPY AMD
```

```
$ python ratewatch.py batch invoices.txt
            1,200.00 USD  ->  1,040.04 EUR            @ 0.866698
              850.00 GBP  ->  1,146.08 USD            @ 1.34833
                0.25 BTC  ->  15,603.75 USD           @ 62,415.00
               2,500 JPY  ->  5,792.89 AMD            @ 2.31716

4 converted, 0 failed — cache, 1 minute old (fetched 2026-08-03 08:56 UTC)
```

### `history [-n N] [--clear]`

Every conversion is appended to a JSON Lines log (disable per-run with
`--no-log`).

```
$ python ratewatch.py history -n 5
WHEN                 CONVERSION                   RATES
2026-08-03 08:57:52  1,200.00 USD -> 1,040.04 EUR fresh-cache
2026-08-03 08:57:52  850.00 GBP -> 1,146.08 USD   fresh-cache
2026-08-03 08:57:52  0.25 BTC -> 15,603.75 USD    fresh-cache
```

---

## How the caching works

This is the heart of the project, so it is worth spelling out.

All rates are stored **relative to one base currency (USD)** in a single JSON
snapshot that carries its own `fetched_at` timestamp. Two things follow from
that:

1. **Any pair is a local calculation.** `rate(A→B) == rates[B] / rates[A]`, so
   converting GBP→JPY needs no request even though nothing was fetched for that
   pair. One snapshot covers all ~38,000 combinations.
2. **Freshness is a property of the whole file**, answered by comparing
   `fetched_at` to the clock — no network round-trip to find out whether a
   refresh is needed.

On every run that needs rates, this policy applies in order:

| Situation | What happens |
| --- | --- |
| `--offline` | Use the cache at any age, never touch the network. Errors only if no cache exists at all. |
| Cache younger than `--max-age` | Use it. No request is made. |
| Cache missing, older than `--max-age`, or `--refresh` given | Fetch, then write the cache. |
| Fetch failed but a cache exists | Fall back to the stale cache, print a warning, and label the output `STALE`. |
| Fetch failed and no cache exists | Fail with a clear message. |

The default `--max-age` is 3600s. The fiat provider only publishes once a day,
so an hour is already generous; `--max-age 0` forces a refetch every time.

Two details that matter more than they look:

- **Writes are atomic.** The snapshot is written to a temporary file and then
  renamed over the real one, so an interrupted run can never leave a
  half-written cache for the next run to trip over.
- **A corrupt cache is not fatal.** If the file cannot be parsed, RateWatch warns,
  treats it as a cache miss, and rebuilds it.

The cached rates are also *explained* rather than silently used: every command
ends with a line saying where the numbers came from and how old they are.

## Money and precision

Exchange rates arrive from JSON as floats, but rounding money with binary floats
is how you end up a cent short. Every rate is lifted into `Decimal` via its
string form before any arithmetic, and results are rounded **half-up** — what
people actually expect from cash — at the number of decimals the target currency
really uses:

| Currency kind | Decimals | Example |
| --- | --- | --- |
| Most fiat | 2 | `1,234,567.89 EUR` |
| JPY, KRW, ISK, XAF… | 0 | `15,000 JPY` |
| BHD, KWD, OMR… | 3 | `37.679 BHD` |
| Crypto | up to 8 | `0.016 BTC` |

Exchange rates themselves span many orders of magnitude — about `0.87` for
USD/EUR but `0.000016` for USD/BTC — so rate precision scales with magnitude to
keep roughly six significant digits instead of showing `0.00`.

The `--json` output keeps values **unrounded** as strings, with a separate
`formatted` block for display, so nothing downstream inherits a display
rounding decision:

```json
{
  "amount": "250",
  "from": "EUR",
  "to": "JPY",
  "rate": "182.3189634682438404150003808",
  "result": "45579.74086706096010375009520",
  "formatted": { "amount": "250.00 EUR", "result": "45,580 JPY", "rate": "182.319" },
  "rates": { "status": "fresh-cache", "stale": false, "age_seconds": 176.2 }
}
```

## APIs used

| Data | Provider | Key required |
| --- | --- | --- |
| Fiat rates (~166 currencies, daily) | [open.er-api.com](https://www.exchangerate-api.com/docs/free) | No |
| Currency display names | [openexchangerates.org](https://openexchangerates.org) (static list) | No |
| Crypto spot prices (30 coins) | [CoinGecko](https://www.coingecko.com/en/api) | No |

Only the fiat feed is required. Names and crypto prices are best-effort: if
CoinGecko rate-limits the request (a plain HTTP 429 is common on the free tier),
you still get a usable fiat snapshot plus a warning on stderr.

The crypto list is curated in `src/config.py` rather than resolved at runtime,
because ticker symbols are not unique across the thousands of coins CoinGecko
lists. Adding a coin is a one-line change.

## Project structure

```
ratewatch/
├── ratewatch.py           # convenience launcher
├── src/
│   ├── main.py            # argparse CLI, output formatting
│   ├── api_client.py      # fetches and normalises both providers
│   ├── cache.py           # cache file + the freshness policy
│   ├── converter.py       # conversion maths, lookup, money formatting
│   ├── history.py         # JSON Lines query log
│   ├── models.py          # RateSnapshot / CurrencyInfo
│   ├── config.py          # endpoints, currency tables, defaults
│   └── errors.py          # exception hierarchy
├── data/                  # cache + query log (gitignored, created at runtime)
├── tests/
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

The layering is one-directional: `config → models → {cache, api_client} →
converter → main`. The freshness policy in `cache.py` takes the fetcher as a
callable, so it never imports the HTTP layer and every branch of it can be
tested with a plain function.

## Data files

Both live in `data/` and are gitignored, since they are regenerated on demand:

- `rates_cache.json` — the current snapshot.
- `query_log.jsonl` — one JSON object per conversion.

Use `--data-dir PATH` to put them somewhere else.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

148 tests, none of which touch the network — the API client is driven by a fake
HTTP session and the cache policy by stub fetchers, so provider outages,
timeouts, HTTP 429s, corrupt cache files and BOM-prefixed batch files are all
covered deterministically.

## Ideas for later

- Historical rate charts with `matplotlib`
- A favorites list for frequently used pairs
- Percentage change since the previous snapshot
- Shell completion for currency codes

## Notes

Rates come from free public feeds and the fiat side updates once a day. Good for
budgeting, invoices and general curiosity; not intended for trading decisions.

## License

MIT
