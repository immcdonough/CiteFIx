"""Tests for citation formatting service."""

import pytest

from app.models.schemas import Citation, CitationStyle
from app.services.citation_formatter import (
    format_citation,
    format_citations_batch,
    learn_format_from_examples,
    STYLE_TEMPLATES,
)


class TestFormatCitation:
    """Tests for format_citation function."""

    def test_format_apa_basic(self):
        """Test basic APA formatting."""
        citation = Citation(
            id="smith_2020",
            raw_text="original",
            authors=["Smith, John A."],
            title="Article title here",
            year=2020,
            journal="Journal of Testing",
            volume="10",
            issue="2",
            pages="45-67",
        )

        pattern = STYLE_TEMPLATES[CitationStyle.APA]
        result = format_citation(citation, pattern)

        assert "Smith" in result
        assert "2020" in result
        assert "Article title here" in result

    def test_format_with_doi(self):
        """Test formatting with DOI."""
        citation = Citation(
            id="test",
            raw_text="original",
            authors=["Smith, John"],
            title="Title",
            year=2020,
            doi="10.1234/test",
        )

        pattern = STYLE_TEMPLATES[CitationStyle.APA]
        result = format_citation(citation, pattern)

        assert "https://doi.org/10.1234/test" in result

    def test_format_multiple_authors(self):
        """Test formatting with multiple authors."""
        citation = Citation(
            id="test",
            raw_text="original",
            authors=["Smith, John", "Jones, Jane", "Williams, Bob"],
            title="Title",
            year=2020,
        )

        pattern = STYLE_TEMPLATES[CitationStyle.APA]
        result = format_citation(citation, pattern)

        # Should have author separator
        assert "&" in result or "and" in result.lower()


class TestLearnFormat:
    """Tests for learning format from examples."""

    def test_learn_from_apa_examples(self):
        """Test learning APA-like format from examples."""
        examples = [
            "Smith, J. A. (2020). Article title. Journal Name, 10(2), 45-67.",
            "Jones, B. C. (2019). Another title. Other Journal, 5(1), 10-20.",
        ]

        pattern = learn_format_from_examples(examples)

        # Should detect parenthetical year
        assert "({year})" in pattern.year_format

    def test_learn_from_empty(self):
        """Test learning from empty examples returns default."""
        pattern = learn_format_from_examples([])

        # Should return APA defaults
        assert pattern.year_format == "({year})"


class TestFormatBatch:
    """Tests for batch formatting."""

    def test_format_batch_apa(self):
        """Test batch formatting with APA style."""
        citations = [
            Citation(
                id="1",
                raw_text="",
                authors=["Smith, J."],
                title="First",
                year=2020,
            ),
            Citation(
                id="2",
                raw_text="",
                authors=["Jones, B."],
                title="Second",
                year=2019,
            ),
        ]

        results = format_citations_batch(citations, style=CitationStyle.APA)

        assert len(results) == 2
        assert all("(" in r and ")" in r for r in results)  # Year in parens

    def test_format_batch_with_examples(self):
        """Test batch formatting with custom examples."""
        citations = [
            Citation(
                id="1",
                raw_text="",
                authors=["Smith, J."],
                title="Title",
                year=2020,
            ),
        ]

        examples = [
            "Smith J (2020) Title. Journal 10:1-10.",
        ]

        results = format_citations_batch(
            citations,
            style=CitationStyle.CUSTOM,
            examples=examples,
        )

        assert len(results) == 1
