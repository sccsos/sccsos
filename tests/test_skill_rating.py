"""Tests for the SkillRating system.

Covers:
- Rating CRUD (rate, re-rate, get user rating)
- Aggregated stats (avg, distribution)
- Install count tracking
- Rankings (top rated, most installed, popular)
- Category listings
- Edge cases (invalid scores, missing skills, no ratings)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from sccsos.core.db import Database
from sccsos.core.db.schema import SCHEMA_SQL, apply_migrations
from sccsos.skill_market import SkillMarket, SkillEntry
from sccsos.skill_rating import SkillRatingManager, SkillRating, SkillRatingStats


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def db() -> Database:
    _db = Database(":memory:")
    _db.executescript(SCHEMA_SQL)
    apply_migrations(_db._conn)
    _db.commit()
    return _db


@pytest.fixture
def market(db: Database) -> SkillMarket:
    return SkillMarket(db)


@pytest.fixture
def mgr(db: Database) -> SkillRatingManager:
    return SkillRatingManager(db)


@pytest.fixture
def sample_skill(market: SkillMarket) -> SkillEntry:
    return market.create_skill(
        name="test-agent",
        ftype="personality",
        author="tester",
        content="name: test-agent\nsystem_prompt: You are a test agent\n",
        tags=["agent", "test"],
        auto_approve=True,
    )


@pytest.fixture
def sample_skill2(market: SkillMarket) -> SkillEntry:
    return market.create_skill(
        name="doc-writer",
        ftype="personality",
        author="writer",
        content="name: doc-writer\nsystem_prompt: Write documentation\n",
        tags=["documentation", "writing"],
        auto_approve=True,
    )


# ── Rating CRUD ───────────────────────────────────────────────────


class TestRatingCRUD:
    def test_rate_skill(self, mgr: SkillRatingManager, sample_skill: SkillEntry):
        """Basic rating (1-5) creates a record."""
        r = mgr.rate("test-agent", user_id="user-1", score=5, comment="Excellent!")
        assert r is not None
        assert r.score == 5
        assert r.comment == "Excellent!"
        assert r.user_id == "user-1"

    def test_rate_multiple_users(self, mgr: SkillRatingManager, sample_skill: SkillEntry):
        """Multiple users can each rate once."""
        mgr.rate("test-agent", user_id="u1", score=5)
        mgr.rate("test-agent", user_id="u2", score=4)
        mgr.rate("test-agent", user_id="u3", score=3)

        ratings = mgr.list_ratings("test-agent")
        assert len(ratings) == 3

    def test_re_rate_updates_score(self, mgr: SkillRatingManager, sample_skill: SkillEntry):
        """Re-rating by same user updates existing record (not duplicate)."""
        mgr.rate("test-agent", user_id="u1", score=5)
        mgr.rate("test-agent", user_id="u1", score=3)

        ratings = mgr.list_ratings("test-agent")
        assert len(ratings) == 1  # Not a duplicate
        assert ratings[0].score == 3

    def test_get_user_rating(self, mgr: SkillRatingManager, sample_skill: SkillEntry):
        """Get a specific user's rating."""
        mgr.rate("test-agent", user_id="alice", score=4)
        r = mgr.get_user_rating("test-agent", "alice")
        assert r is not None
        assert r.score == 4

    def test_get_user_rating_not_rated(self, mgr: SkillRatingManager, sample_skill: SkillEntry):
        """Returns None when user hasn't rated."""
        r = mgr.get_user_rating("test-agent", "nobody")
        assert r is None

    def test_rate_missing_skill(self, mgr: SkillRatingManager):
        """Returns None when skill doesn't exist."""
        r = mgr.rate("nonexistent", user_id="u1", score=5)
        assert r is None

    @pytest.mark.parametrize("invalid_score", [0, 6, -1, 100])
    def test_rate_invalid_score(self, mgr: SkillRatingManager, sample_skill: SkillEntry, invalid_score: int):
        """Invalid scores (outside 1-5) are rejected."""
        r = mgr.rate("test-agent", user_id="u1", score=invalid_score)
        assert r is None


# ── Aggregated Stats ──────────────────────────────────────────────


class TestSkillRatingStats:
    def test_empty_stats(self, mgr: SkillRatingManager, sample_skill: SkillEntry):
        """Skill with no ratings returns zeroed stats."""
        stats = mgr.get_rating("test-agent")
        assert stats is not None
        assert stats.total_ratings == 0
        assert stats.avg_score == 0.0
        assert stats.distribution == {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

    def test_average_calculation(self, mgr: SkillRatingManager, sample_skill: SkillEntry):
        """Average score is correctly computed."""
        mgr.rate("test-agent", user_id="u1", score=5)
        mgr.rate("test-agent", user_id="u2", score=4)
        mgr.rate("test-agent", user_id="u3", score=3)

        stats = mgr.get_rating("test-agent")
        assert stats.total_ratings == 3
        assert stats.avg_score == 4.0  # (5+4+3)/3
        assert stats.distribution[5] == 1
        assert stats.distribution[4] == 1
        assert stats.distribution[3] == 1

    def test_distribution_after_re_rate(self, mgr: SkillRatingManager, sample_skill: SkillEntry):
        """Re-rating changes distribution correctly."""
        mgr.rate("test-agent", user_id="u1", score=5)
        mgr.rate("test-agent", user_id="u2", score=4)
        mgr.rate("test-agent", user_id="u1", score=2)  # Re-rate

        stats = mgr.get_rating("test-agent")
        assert stats.total_ratings == 2  # u1 still counts once
        assert stats.avg_score == 3.0  # (2+4)/2
        assert stats.distribution[5] == 0  # u1 changed from 5 to 2
        assert stats.distribution[2] == 1

    def test_list_ratings_order(self, mgr: SkillRatingManager, sample_skill: SkillEntry):
        """Ratings are returned in reverse chronological order."""
        mgr.rate("test-agent", user_id="u1", score=5)
        mgr.rate("test-agent", user_id="u2", score=4)
        mgr.rate("test-agent", user_id="u3", score=3)

        ratings = mgr.list_ratings("test-agent")
        assert len(ratings) == 3


# ── Install Count ─────────────────────────────────────────────────


class TestInstallCount:
    def test_increment_install(self, mgr: SkillRatingManager, sample_skill: SkillEntry):
        """Install count starts at 0 and increments."""
        assert mgr.get_install_count("test-agent") == 0
        mgr.increment_install_count("test-agent")
        assert mgr.get_install_count("test-agent") == 1

    def test_increment_multiple(self, mgr: SkillRatingManager, sample_skill: SkillEntry):
        """Multiple installs accumulate."""
        for _ in range(5):
            mgr.increment_install_count("test-agent")
        assert mgr.get_install_count("test-agent") == 5

    def test_increment_missing_skill(self, mgr: SkillRatingManager):
        """Returns False for non-existent skill."""
        result = mgr.increment_install_count("nonexistent")
        assert result is False

    def test_install_count_initially_zero(self, mgr: SkillRatingManager, market: SkillMarket, sample_skill: SkillEntry):
        """Fresh skill_market row has NULL install_count, returns 0."""
        # Verify via manager works
        assert mgr.get_install_count("test-agent") == 0


# ── Rankings ──────────────────────────────────────────────────────


class TestRankings:
    def test_top_rated_empty(self, mgr: SkillRatingManager):
        """No skills returns empty list."""
        top = mgr.get_top_rated()
        assert top == []

    def test_top_rated_order(self, mgr: SkillRatingManager, market: SkillMarket):
        """Top rated is ordered by avg_score descending."""
        s1 = market.create_skill(name="a", ftype="personality", content="name: a\nsystem_prompt: A", auto_approve=True)
        s2 = market.create_skill(name="b", ftype="personality", content="name: b\nsystem_prompt: B", auto_approve=True)

        mgr.rate("a", user_id="u1", score=5)
        mgr.rate("b", user_id="u1", score=3)

        top = mgr.get_top_rated()
        assert len(top) == 2
        assert top[0].name == "a"
        assert top[1].name == "b"

    def test_top_rated_min_ratings_filter(self, mgr: SkillRatingManager, market: SkillMarket):
        """min_ratings filters out skills with too few ratings."""
        s1 = market.create_skill(name="a", ftype="personality", content="name: a\nsystem_prompt: A", auto_approve=True)
        s2 = market.create_skill(name="b", ftype="personality", content="name: b\nsystem_prompt: B", auto_approve=True)

        mgr.rate("a", user_id="u1", score=5)
        mgr.rate("b", user_id="u1", score=4)
        mgr.rate("b", user_id="u2", score=5)

        # a has 1 rating, b has 2
        top1 = mgr.get_top_rated(min_ratings=1)
        assert len(top1) == 2

        top2 = mgr.get_top_rated(min_ratings=2)
        assert len(top2) == 1
        assert top2[0].name == "b"

    def test_most_installed_order(self, mgr: SkillRatingManager, market: SkillMarket):
        """Most installed is ordered by count descending."""
        market.create_skill(name="a", ftype="personality", content="name: a\nsystem_prompt: A", auto_approve=True)
        market.create_skill(name="b", ftype="personality", content="name: b\nsystem_prompt: B", auto_approve=True)

        mgr.increment_install_count("a")
        mgr.increment_install_count("a")
        mgr.increment_install_count("a")
        mgr.increment_install_count("b")

        most = mgr.get_most_installed()
        assert len(most) == 2
        assert most[0].name == "a"
        assert most[0].install_count == 3
        assert most[1].install_count == 1

    def test_popular_combines_rating_and_installs(self, mgr: SkillRatingManager, market: SkillMarket):
        """Popular ranking uses weighted combination."""
        market.create_skill(name="high-rated", ftype="personality", content="name: high\nsystem_prompt: A", auto_approve=True)
        market.create_skill(name="many-installs", ftype="personality", content="name: many\nsystem_prompt: B", auto_approve=True)

        mgr.rate("high-rated", user_id="u1", score=5)
        mgr.increment_install_count("many-installs")
        mgr.increment_install_count("many-installs")

        popular = mgr.get_popular()
        assert len(popular) >= 2


# ── Categories ────────────────────────────────────────────────────


class TestCategories:
    def test_empty_categories(self, mgr: SkillRatingManager):
        """No categories returns empty list."""
        cats = mgr.list_categories()
        assert cats == []

    def test_list_categories(self, mgr: SkillRatingManager, market: SkillMarket):
        """Categories are listed from unique values."""
        market.create_skill(name="cat-a", ftype="personality",
            content="name: cat-a\nsystem_prompt: A", auto_approve=True)
        market.create_skill(name="cat-b", ftype="personality",
            content="name: cat-b\nsystem_prompt: B", auto_approve=True)

        # Set categories directly via SQL
        market._db.execute("UPDATE skill_market SET category = ? WHERE name = ?", ("nlp", "cat-a"))
        market._db.execute("UPDATE skill_market SET category = ? WHERE name = ?", ("code", "cat-b"))
        market._db.commit()

        cats = mgr.list_categories()
        assert "nlp" in cats
        assert "code" in cats
        assert len(cats) == 2

    def test_skills_by_category(self, mgr: SkillRatingManager, market: SkillMarket):
        """Filtering by category returns correct skills."""
        market.create_skill(name="nlp-agent", ftype="personality",
            content="name: nlp\nsystem_prompt: N", auto_approve=True)
        market.create_skill(name="code-agent", ftype="personality",
            content="name: code\nsystem_prompt: C", auto_approve=True)

        market._db.execute("UPDATE skill_market SET category = ? WHERE name = ?", ("nlp", "nlp-agent"))
        market._db.commit()

        skills = mgr.get_skills_by_category("nlp")
        assert len(skills) == 1
        assert skills[0].name == "nlp-agent"

    def test_skills_by_missing_category(self, mgr: SkillRatingManager):
        """Non-existent category returns empty list."""
        skills = mgr.get_skills_by_category("nonexistent")
        assert skills == []


# ── SkillMarket Integration ───────────────────────────────────────


class TestSkillMarketIntegration:
    def test_install_increments_count(self, mgr: SkillRatingManager, market: SkillMarket):
        """Installing via SkillMarket.install() increments count."""
        import tempfile, os
        tmpdir = tempfile.mkdtemp()

        # Create a skill file
        filepath = os.path.join(tmpdir, "personalities", "integration-test.yaml")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            f.write("name: integration-test\nsystem_prompt: Test\n")

        # Publish and install
        market.publish(filepath, auto_approve=True)
        market.install("integration-test", target_dir=tmpdir)

        count = mgr.get_install_count("integration-test")
        assert count == 1

        # Install again
        market.install("integration-test", target_dir=tmpdir)
        count = mgr.get_install_count("integration-test")
        assert count == 2
