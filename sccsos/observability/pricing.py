"""Pricing table — model cost lookup with external JSON file support.

Provides a PricingTable class that loads LLM pricing from a JSON file
with optional TTL-based hot reload. Falls back to built-in defaults
if the file is not found.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

# ── Built-in defaults (used when no external file is configured) ────

FALLBACK_PRICING: dict[str, tuple[float, float]] = {
    "deepseek-v4-flash":   (0.14, 0.28),
    "deepseek-v4-pro":     (0.44, 0.87),
    "deepseek-chat":       (0.14, 0.28),
    "deepseek-reasoner":   (0.55, 2.19),
    "gpt-4o":             (2.50, 10.00),
    "gpt-4o-mini":        (0.15, 0.60),
    "claude-sonnet-4":     (3.00, 15.00),
    "claude-haiku-3.5":   (0.80, 4.00),
    "gemini-2.5-flash":    (0.30, 2.50),
    "gemini-2.5-pro":     (1.25, 10.00),
}

DEFAULT_INPUT_PRICE = 0.50
DEFAULT_OUTPUT_PRICE = 2.00


class PricingTable:
    """Loads and caches model pricing from an external JSON file.

    Usage:
        pricing = PricingTable("config/pricing.json", ttl_seconds=300)
        input_price, output_price = pricing.get("gpt-4o")
        cost = pricing.estimate_cost("gpt-4o", tokens_in=500, tokens_out=200)

    The JSON file format:
    {
        "models": {
            "model-name": [input_price_per_1M, output_price_per_1M],
            ...
        },
        "default_input_price": 0.50,
        "default_output_price": 2.00,
        "version": 1
    }
    """

    def __init__(self, path: Optional[str | Path] = None,
                 ttl_seconds: int = 300):
        self._path = Path(path) if path else None
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, float]] = {}
        self._default_input = DEFAULT_INPUT_PRICE
        self._default_output = DEFAULT_OUTPUT_PRICE
        self._loaded_at: float = 0.0

        if self._path and self._path.exists():
            self._load()
        else:
            self._cache = dict(FALLBACK_PRICING)

    # ── Public API ───────────────────────────────────────────────

    def get(self, model: str) -> tuple[float, float]:
        """Get (input_price_per_1M, output_price_per_1M) for a model.

        Returns defaults for unknown models. Hot-reloads the file
        if TTL has expired.
        """
        self._refresh_if_stale()
        pricing = self._cache.get(model)
        if pricing is not None:
            return pricing
        return (self._default_input, self._default_output)

    def get_input_price(self, model: str) -> float:
        return self.get(model)[0]

    def get_output_price(self, model: str) -> float:
        return self.get(model)[1]

    def estimate_cost(self, model: str, tokens_input: int,
                      tokens_output: int) -> float:
        """Estimate USD cost for a model call."""
        inp, outp = self.get(model)
        input_cost = (tokens_input / 1_000_000) * inp
        output_cost = (tokens_output / 1_000_000) * outp
        return round(input_cost + output_cost, 6)

    def list_models(self) -> list[str]:
        """Return sorted list of known model names."""
        self._refresh_if_stale()
        return sorted(self._cache.keys())

    def add_model(self, model: str, input_price: float,
                  output_price: float) -> None:
        """Add or update a model's pricing in the cache (runtime only)."""
        self._cache[model] = (input_price, output_price)

    def reload(self) -> None:
        """Force-reload from the JSON file."""
        if self._path and self._path.exists():
            self._load()

    # ── Internal ──────────────────────────────────────────────────

    def _refresh_if_stale(self) -> None:
        """Reload from disk if TTL has expired."""
        if not self._path or not self._path.exists():
            return
        if time.monotonic() - self._loaded_at > self._ttl:
            try:
                self._load()
            except Exception:
                pass  # Keep current cache on reload failure

    def _load(self) -> None:
        """Load pricing data from the JSON file."""
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            # Fall back to built-in defaults
            self._cache = dict(FALLBACK_PRICING)
            return

        models = data.get("models", {})
        loaded: dict[str, tuple[float, float]] = {}
        for name, prices in models.items():
            if isinstance(prices, list) and len(prices) >= 2:
                loaded[name] = (float(prices[0]), float(prices[1]))

        self._cache = loaded
        self._default_input = float(data.get("default_input_price",
                                              DEFAULT_INPUT_PRICE))
        self._default_output = float(data.get("default_output_price",
                                               DEFAULT_OUTPUT_PRICE))
        self._loaded_at = time.monotonic()

    def __repr__(self) -> str:
        return (f"<PricingTable {len(self._cache)} models, "
                f"path={self._path}, ttl={self._ttl}s>")


# ── Module-level singleton (lazy, kept for backward compatibility) ──
# DEPRECATED in v0.6.0. Will be removed in v0.8.0.
# Create PricingTable instances directly and inject via
# ``Auditor.__init__(pricing=...)`` instead.

_PRICING_TABLE: PricingTable | None = None


def get_pricing(path: Optional[str | Path] = None,
                ttl: int = 300) -> PricingTable:
    """Get or create the global PricingTable singleton.

    .. deprecated:: 0.6.0
       Use ``PricingTable(path, ttl_seconds=ttl)`` with dependency injection instead.
    """
    global _PRICING_TABLE
    if _PRICING_TABLE is None:
        _PRICING_TABLE = PricingTable(path=path, ttl_seconds=ttl)
    return _PRICING_TABLE
