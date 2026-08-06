"""Exception types used across RateWatch.

Every error the CLI is expected to recover from derives from :class:`RateWatchError`,
so ``main`` can catch a single type and print a clean message instead of a traceback.
"""

from __future__ import annotations


class RateWatchError(Exception):
    """Base class for all expected RateWatch failures."""


class ApiError(RateWatchError):
    """A rate provider could not be reached or returned something unusable."""


class CacheError(RateWatchError):
    """The local cache file could not be read or written."""


class NoRatesAvailableError(RateWatchError):
    """No rates could be obtained: the network failed and no cache exists."""


class UnknownCurrencyError(RateWatchError):
    """A currency code is not present in the current rate snapshot."""

    def __init__(self, code: str, suggestions: list[str] | None = None) -> None:
        self.code = code
        self.suggestions = suggestions or []
        message = f"unknown currency code {code!r}"
        if self.suggestions:
            message += f" (did you mean: {', '.join(self.suggestions)}?)"
        else:
            message += " — run `ratewatch list` to see supported codes"
        super().__init__(message)
