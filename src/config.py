"""Static configuration: file locations, endpoints and currency metadata tables."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
CACHE_FILENAME = "rates_cache.json"
HISTORY_FILENAME = "query_log.jsonl"

#: Everything is stored relative to this currency, so any pair can be derived
#: from a single snapshot: rate(A -> B) == rates[B] / rates[A].
BASE_CURRENCY = "USD"

#: How long a cached snapshot is considered fresh, in seconds.
#: The fiat provider only refreshes once a day, so an hour is generous.
DEFAULT_MAX_AGE = 3600

#: Per-request network timeout, in seconds.
REQUEST_TIMEOUT = 10

# --- Endpoints (all free, no API key required) -------------------------------

#: Daily fiat reference rates for ~160 ISO 4217 currencies.
FIAT_RATES_URL = "https://open.er-api.com/v6/latest/{base}"

#: Static ISO code -> display name map, used to label the fiat codes.
FIAT_NAMES_URL = "https://openexchangerates.org/api/currencies.json"

#: CoinGecko spot prices; queried with an explicit list of coin ids.
CRYPTO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"

USER_AGENT = "RateWatch/1.0 (+https://github.com/)"

# --- Crypto coverage ---------------------------------------------------------

#: Ticker -> (CoinGecko id, display name).
#:
#: CoinGecko lists thousands of coins and ticker symbols are not unique across
#: them, so RateWatch ships a curated list instead of resolving symbols at
#: runtime. Adding a coin is a one-line change here.
CRYPTO_COINS: dict[str, tuple[str, str]] = {
    "BTC": ("bitcoin", "Bitcoin"),
    "ETH": ("ethereum", "Ethereum"),
    "USDT": ("tether", "Tether"),
    "BNB": ("binancecoin", "BNB"),
    "SOL": ("solana", "Solana"),
    "XRP": ("ripple", "XRP"),
    "USDC": ("usd-coin", "USD Coin"),
    "ADA": ("cardano", "Cardano"),
    "DOGE": ("dogecoin", "Dogecoin"),
    "TRX": ("tron", "TRON"),
    "TON": ("the-open-network", "Toncoin"),
    "AVAX": ("avalanche-2", "Avalanche"),
    "DOT": ("polkadot", "Polkadot"),
    "MATIC": ("matic-network", "Polygon"),
    "LINK": ("chainlink", "Chainlink"),
    "SHIB": ("shiba-inu", "Shiba Inu"),
    "LTC": ("litecoin", "Litecoin"),
    "BCH": ("bitcoin-cash", "Bitcoin Cash"),
    "UNI": ("uniswap", "Uniswap"),
    "ATOM": ("cosmos", "Cosmos Hub"),
    "XLM": ("stellar", "Stellar"),
    "XMR": ("monero", "Monero"),
    "ETC": ("ethereum-classic", "Ethereum Classic"),
    "NEAR": ("near", "NEAR Protocol"),
    "APT": ("aptos", "Aptos"),
    "ARB": ("arbitrum", "Arbitrum"),
    "OP": ("optimism", "Optimism"),
    "FIL": ("filecoin", "Filecoin"),
    "ALGO": ("algorand", "Algorand"),
    "VET": ("vechain", "VeChain"),
}

# --- Money formatting --------------------------------------------------------

#: ISO 4217 currencies with no minor unit — formatted without decimals.
ZERO_DECIMAL_CURRENCIES = frozenset(
    {
        "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW",
        "PYG", "RWF", "UGX", "UYI", "VND", "VUV", "XAF", "XOF", "XPF",
    }
)

#: ISO 4217 currencies with three decimal places.
THREE_DECIMAL_CURRENCIES = frozenset(
    {"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"}
)

#: Default decimals for anything not listed above.
FIAT_DECIMALS = 2

#: Crypto amounts are shown with more precision — a satoshi is 1e-8 BTC.
CRYPTO_DECIMALS = 8

KIND_FIAT = "fiat"
KIND_CRYPTO = "crypto"
