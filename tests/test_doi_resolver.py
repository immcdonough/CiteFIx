"""Tests for DOI resolution service."""

import pytest

from app.models.schemas import Citation
from app.services.doi_resolver import DOIResolver, DOIMatch


class TestDOIResolver:
    """Tests for DOIResolver class."""

    def test_cache_key_generation(self):
        """Test that cache keys are generated consistently."""
        resolver = DOIResolver()

        citation = Citation(
            id="test",
            raw_text="Test citation",
            authors=["Smith, John", "Jones, Jane"],
            title="Test Article Title",
            year=2020,
        )

        key1 = resolver._make_cache_key(citation)
        key2 = resolver._make_cache_key(citation)

        assert key1 == key2
        assert "test article title" in key1.lower()
        assert "smith" in key1.lower()
        assert "2020" in key1

    def test_string_similarity(self):
        """Test string similarity calculation."""
        resolver = DOIResolver()

        # Identical strings
        assert resolver._string_similarity("hello world", "hello world") == 1.0

        # Partial overlap
        sim = resolver._string_similarity("hello world", "hello there")
        assert 0 < sim < 1

        # No overlap
        sim = resolver._string_similarity("abc", "xyz")
        assert sim == 0.0

    def test_author_match_score(self):
        """Test author matching score."""
        resolver = DOIResolver()

        citation_authors = ["Smith, John", "Jones, Jane"]
        item_authors = [
            {"family": "Smith", "given": "John"},
            {"family": "Jones", "given": "Jane"},
        ]

        score = resolver._author_match_score(citation_authors, item_authors)
        assert score == 1.0

    def test_author_match_partial(self):
        """Test partial author matching."""
        resolver = DOIResolver()

        citation_authors = ["Smith, John", "Jones, Jane"]
        item_authors = [
            {"family": "Smith", "given": "John"},
            {"family": "Williams", "given": "Bob"},
        ]

        score = resolver._author_match_score(citation_authors, item_authors)
        assert 0 < score < 1

    def test_extract_year(self):
        """Test year extraction from CrossRef item."""
        resolver = DOIResolver()

        item = {
            "published-print": {
                "date-parts": [[2020, 5, 15]]
            }
        }

        year = resolver._extract_year(item)
        assert year == 2020

    def test_extract_year_online(self):
        """Test year extraction from online publication date."""
        resolver = DOIResolver()

        item = {
            "published-online": {
                "date-parts": [[2019, 12, 1]]
            }
        }

        year = resolver._extract_year(item)
        assert year == 2019

    def test_item_to_match(self):
        """Test conversion of CrossRef item to DOIMatch."""
        resolver = DOIResolver()

        item = {
            "DOI": "10.1234/test",
            "title": ["Test Article Title"],
            "author": [
                {"given": "John", "family": "Smith"},
                {"given": "Jane", "family": "Jones"},
            ],
            "published-print": {
                "date-parts": [[2020]]
            }
        }

        match = resolver._item_to_match(item, confidence=0.9)

        assert match.doi == "10.1234/test"
        assert match.doi_url == "https://doi.org/10.1234/test"
        assert match.title == "Test Article Title"
        assert len(match.authors) == 2
        assert match.year == 2020
        assert match.confidence == 0.9


class TestDOIMatchDataclass:
    """Tests for DOIMatch dataclass."""

    def test_doi_match_creation(self):
        """Test creating a DOIMatch instance."""
        match = DOIMatch(
            doi="10.1234/test",
            doi_url="https://doi.org/10.1234/test",
            title="Test Title",
            authors=["John Smith"],
            year=2020,
            confidence=0.95,
        )

        assert match.doi == "10.1234/test"
        assert match.confidence == 0.95


# Integration tests (require network, marked to skip by default)
@pytest.mark.skip(reason="Requires network access to CrossRef API")
class TestDOIResolverIntegration:
    """Integration tests for DOI resolver."""

    def test_resolve_known_doi(self):
        """Test resolving a known DOI."""
        resolver = DOIResolver()

        citation = Citation(
            id="test",
            raw_text="",
            doi="10.1038/nature12373",  # A real Nature paper
        )

        match = resolver.resolve_citation(citation)

        assert match is not None
        assert match.doi == "10.1038/nature12373"

    def test_search_by_title(self):
        """Test searching by title and author."""
        resolver = DOIResolver()

        citation = Citation(
            id="test",
            raw_text="",
            authors=["Watson, J. D.", "Crick, F. H."],
            title="Molecular structure of nucleic acids",
            year=1953,
        )

        match = resolver.resolve_citation(citation)

        # This famous paper should be found
        assert match is not None
