"""Tests for PricingTable.reload() and _refresh_if_stale()."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest import mock

import pytest

from sccsos.observability.pricing import PricingTable


class TestPricingReload:
    """Coverage for reload() and _refresh_if_stale() code paths."""

    @staticmethod
    def test_reload_with_file(tmp_path: Path) -> None:
        """reload() loads pricing from an existing JSON file.

        Coverage:
            pricing.py:106-109 — reload() when self._path and
            self._path.exists() calls self._load()
        """
        # ── Prepare a pricing JSON file ──────────────────────────
        pricing_file = tmp_path / "pricing.json"
        pricing_file.write_text(
            json.dumps({
                "models": {
                    "test-model": [1.0, 2.0],
                    "another-model": [3.0, 4.0],
                },
            }),
            encoding="utf-8",
        )

        table = PricingTable(path=pricing_file, ttl_seconds=300)

        # Data should have been loaded via __init__
        assert table.get("test-model") == (1.0, 2.0)
        assert table.get("another-model") == (3.0, 4.0)

        # ── Modify the file and call reload() ────────────────────
        pricing_file.write_text(
            json.dumps({
                "models": {
                    "test-model": [5.0, 6.0],
                },
            }),
            encoding="utf-8",
        )
        table.reload()

        # reload() should have refreshed from disk
        assert table.get("test-model") == (5.0, 6.0)
        # "another-model" was removed from the file — falls back to defaults
        assert table.get("another-model") == (
            table._default_input,
            table._default_output,
        )

    @staticmethod
    def test_reload_without_path() -> None:
        """reload() does nothing when PricingTable has no path set.

        Coverage:
            pricing.py:108 — reload() early-returns when
            self._path is None.
        """
        table = PricingTable()

        # Should not raise
        table.reload()

        # Cache should still contain fallback defaults
        assert "gpt-4o" in table._cache
        assert table.get("gpt-4o") == (2.50, 10.00)

    @staticmethod
    def test_refresh_if_stale_no_path() -> None:
        """_refresh_if_stale() returns early when no path is set.

        Coverage:
            pricing.py:115 — early return when self._path is falsy.
        """
        table = PricingTable()

        # Should not raise
        table._refresh_if_stale()

        # Cache unchanged
        assert "deepseek-v4-flash" in table._cache

    @staticmethod
    def test_refresh_if_stale_load_failure() -> None:
        """_refresh_if_stale() keeps current cache when _load() raises.

        Coverage:
            pricing.py:118-121 — try/except Exception: pass
            when TTL expired but _load() unexpectedly fails.
        """
        table = PricingTable()
        # __init__ used FALLBACK_PRICING (no path given)
        initial_cache = dict(table._cache)

        # Set an existing path, force TTL expired, and make _load() throw
        with mock.patch.object(
            PricingTable,
            "_load",
            side_effect=RuntimeError("unexpected disk error"),
        ):
            table._path = Path("/tmp")  # guaranteed to exist on any Unix/macOS
            table._loaded_at = 0.0  # monotonic clock is way past this → TTL expired
            table._refresh_if_stale()

        # Cache should be preserved (exception swallowed)
        assert table._cache == initial_cache
        assert table.get("deepseek-v4-flash") == (0.14, 0.28)
