<div align="center">

# 💱 RateWatch
### Currency & Crypto Converter with Smart Local Caching

A robust command-line currency converter for **fiat currencies** and **cryptocurrencies**
that intelligently caches exchange rates, works offline, and continues operating even
when the network doesn't.

![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![CLI](https://img.shields.io/badge/Interface-CLI-4CAF50?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)
![Tests](https://img.shields.io/badge/Tests-148-success?style=for-the-badge)

</div>

---

## ✨ Overview

**RateWatch** is a professional command-line converter capable of converting
between **196 different currencies**:

- 🌍 **166 fiat currencies** (ISO 4217)
- 💰 **30 major cryptocurrencies**

Every rate is stored relative to a single base currency (**USD**), allowing
**every possible conversion pair** to be calculated locally without additional
network requests.

Even if the internet goes down, RateWatch keeps working using its local cache.

---

## 📸 Example

```console
$ python ratewatch.py convert 100 USD EUR

100.00 USD  ->  86.67 EUR

Rate      1 USD = 0.866698 EUR
Inverse   1 EUR = 1.1538 USD
Rates     cache, 3 minutes old (fetched 2026-08-03 08:56 UTC)
```

---

# 📚 Table of Contents

- Features
- Requirements
- Installation
- Quick Start
- Commands
- Caching Strategy
- Money & Precision
- APIs
- Project Structure
- Data Files
- Tests
- Future Ideas
- License

---

# 🚀 Features

✔ Convert **fiat ↔ fiat**

✔ Convert **fiat ↔ crypto**

✔ Convert **crypto ↔ crypto**

✔ Intelligent local cache

✔ Automatic freshness checking

✔ Offline mode

✔ Automatic stale-cache fallback

✔ Decimal-based financial calculations

✔ Correct currency-specific rounding

✔ Currency search

✔ Batch conversions

✔ Conversion history

✔ JSON output for scripting

✔ Graceful API failure handling

---

# 📦 Requirements

- Python **3.9+**
- requests

```bash
pip install -r requirements.txt
```

No API key required.

---

# ⚡ Quick Start

```bash
python ratewatch.py refresh

python ratewatch.py convert 100 USD EUR

python ratewatch.py convert 0.5 BTC AMD

python ratewatch.py list --kind crypto
```

Package execution works too:

```bash
python -m src.main
```

Windows:

```bash
py ratewatch.py
```

---

# 🖥 Commands

---

## Convert

```console
$ python ratewatch.py convert 0.5 BTC AMD

0.50 BTC  ->  11,426,516.18 AMD

Rate      1 BTC = 22,853,032.36 AMD
Inverse   1 AMD = 0.000000043758 BTC
Rates     cache, just now (fetched 2026-08-03 08:56 UTC)
```

Supports:

- commas in numbers (`1,250.75`)
- case-insensitive currency codes
- typo suggestions

Example:

```console
$ python ratewatch.py convert 10 USD EURO

ratewatch: error:
unknown currency code 'EURO'
(did you mean: EUR?)
```

---

## Rate

```console
$ python ratewatch.py rate EUR JPY

1 EUR = 182.319 JPY

Rates:
cache, 3 minutes old
```

---

## List

```console
$ python ratewatch.py list --search dram

CODE  KIND    NAME

AMD   fiat    Armenian Dram

1 currency (1 fiat)

Base: USD
```

Supports:

- code search
- name search
- fiat filter
- crypto filter

---

## Refresh

Forces a complete refresh.

```console
$ python ratewatch.py refresh

Refreshed 196 rates

166 fiat

30 crypto

Base USD
```

---

## Cache

```console
$ python ratewatch.py cache

Cache file

Fetched

Age

Freshness

Base

Currencies
```

Displays cache metadata without making network requests.

---

## Batch

Convert multiple values from a file.

Example file:

```text
1200 USD EUR
850,GBP,USD
0.25 BTC USD
2500 JPY AMD
```

Run:

```bash
python ratewatch.py batch invoices.txt
```

Blank lines and comments are ignored.

---

## History

```bash
python ratewatch.py history

python ratewatch.py history -n 10

python ratewatch.py history --clear
```

Every conversion is stored as JSON Lines.

---

# 🧠 Smart Caching Strategy

RateWatch stores every exchange rate inside a single JSON snapshot.

Instead of downloading every currency pair individually, all rates are stored
relative to **USD**.

That means:

```
GBP → JPY

=

JPY / GBP
```

No additional API request is needed.

---

## Cache Policy

| Situation | Behavior |
|-----------|----------|
| Offline | Use cache only |
| Fresh cache | Use cache |
| Cache expired | Fetch new snapshot |
| Fetch failed + cache exists | Use stale cache |
| Fetch failed + no cache | Error |

Default maximum cache age:

```
3600 seconds
```

---

## Reliability

### Atomic Writes

The cache is written to a temporary file first and then atomically renamed.

Interrupted writes never leave a corrupted cache.

### Corrupt Cache Recovery

If the cache cannot be parsed:

- warning printed
- cache ignored
- rebuilt automatically

---

# 💰 Money & Precision

Financial calculations use **Decimal**, never binary floating point.

Rounding mode:

```
ROUND_HALF_UP
```

Currency precision:

| Currency | Decimals |
|-----------|-----------|
| Most fiat | 2 |
| JPY, KRW... | 0 |
| BHD, KWD... | 3 |
| Crypto | up to 8 |

Exchange rates preserve roughly **six significant digits**.

---

## JSON Output

Display formatting never affects machine-readable values.

Example:

```json
{
  "amount":"250",
  "rate":"182.3189634682438404150003808",
  "result":"45579.74086706096010375009520"
}
```

---

# 🌐 APIs Used

| Data | Provider | API Key |
|------|----------|----------|
| Fiat rates | open.er-api.com | ❌ |
| Currency names | OpenExchangeRates | ❌ |
| Crypto prices | CoinGecko | ❌ |

CoinGecko is optional.

If it rate-limits the request, fiat conversions continue normally.

---

# 📁 Project Structure

```text
ratewatch/
│
├── ratewatch.py
│
├── src/
│   ├── main.py
│   ├── api_client.py
│   ├── cache.py
│   ├── converter.py
│   ├── history.py
│   ├── models.py
│   ├── config.py
│   └── errors.py
│
├── data/
├── tests/
│
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

Architecture:

```
config

↓

models

↓

cache
api_client

↓

converter

↓

main
```

Each layer depends only on the layer above it, making the project easy to test and maintain.

---

# 📂 Data Files

Generated automatically.

```
data/

├── rates_cache.json

└── query_log.jsonl
```

Use another location:

```bash
--data-dir PATH
```

---

# ✅ Tests

```bash
pip install -r requirements-dev.txt

python -m pytest tests -q
```

**148 deterministic tests**

Covered scenarios include:

- network failures
- provider outages
- HTTP 429
- malformed JSON
- corrupt cache
- stale cache
- timeout handling
- offline mode
- BOM-prefixed batch files

No test touches the real network.

---

# 💡 Future Ideas

- 📈 Historical charts
- ⭐ Favorite conversion pairs
- 📊 Daily change percentages
- 🐚 Shell completion
- 📱 TUI interface
- 🌍 Multiple base currencies

---

# 📝 Notes

RateWatch uses free public APIs.

Exchange rates are intended for:

- budgeting
- invoices
- travel
- education

They are **not intended for trading decisions**.

---

# 📄 License

MIT

---

<div align="center">

**Built with Python ❤️**

*A reliable CLI currency converter that keeps working—even when the internet doesn't.*

</div>
