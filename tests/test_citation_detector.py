"""Tests for citation detection service."""

import pytest

from app.models.schemas import CitationType
from app.services.citation_detector import (
    detect_citations,
    parse_references,
    match_citations_to_references,
)


class TestDetectCitations:
    """Tests for detect_citations function."""

    def test_detect_author_year_parenthetical(self):
        """Test detection of (Author, Year) citations."""
        text = "As shown by previous research (Smith, 2020), the results are significant."
        result = detect_citations(text)

        assert len(result.in_text_citations) == 1
        assert result.in_text_citations[0].text == "(Smith, 2020)"
        assert result.in_text_citations[0].citation_type == CitationType.AUTHOR_YEAR

    def test_detect_author_year_multiple_authors(self):
        """Test detection of citations with multiple authors."""
        text = "According to (Smith & Jones, 2020) and (Williams et al., 2019)."
        result = detect_citations(text)

        assert len(result.in_text_citations) == 2
        texts = [c.text for c in result.in_text_citations]
        assert "(Smith & Jones, 2020)" in texts
        assert "(Williams et al., 2019)" in texts

    def test_detect_numeric_citations(self):
        """Test detection of numeric [1] style citations."""
        text = "Previous studies [1] have shown that [2, 3] this is true [4-6]."
        result = detect_citations(text)

        assert len(result.in_text_citations) == 3
        assert result.detected_type == CitationType.NUMERIC

    def test_detect_numeric_range(self):
        """Test that numeric ranges are expanded."""
        text = "As shown in [1-3]."
        result = detect_citations(text)

        assert len(result.in_text_citations) == 1
        assert result.in_text_citations[0].reference_ids == ["1", "2", "3"]

    def test_no_citations(self):
        """Test with text containing no citations."""
        text = "This is plain text with no citations."
        result = detect_citations(text)

        assert len(result.in_text_citations) == 0


class TestParseReferences:
    """Tests for parse_references function."""

    def test_parse_apa_reference(self):
        """Test parsing APA-style reference."""
        entries = [
            "Smith, J. A. (2020). Article title here. Journal of Testing, 10(2), 45-67."
        ]
        result = parse_references(entries)

        assert len(result) == 1
        ref = result[0]
        assert ref.year == 2020
        assert "Smith" in ref.authors[0]
        assert ref.title == "Article title here"

    def test_parse_reference_with_doi(self):
        """Test parsing reference with DOI."""
        entries = [
            "Smith, J. (2020). Title. Journal, 1(1), 1-10. https://doi.org/10.1234/test.123"
        ]
        result = parse_references(entries)

        assert len(result) == 1
        assert result[0].doi == "10.1234/test.123"
        assert result[0].doi_url == "https://doi.org/10.1234/test.123"

    def test_parse_numbered_reference(self):
        """Test parsing numbered reference style."""
        entries = [
            "1. Smith J, Jones B. Article title. Journal. 2020;10(2):45-67."
        ]
        result = parse_references(entries)

        assert len(result) == 1
        ref = result[0]
        assert ref.year == 2020

    def test_parse_multiple_references(self):
        """Test parsing multiple references."""
        entries = [
            "Smith, J. (2020). First article. Journal A, 1, 1-10.",
            "Jones, B. (2019). Second article. Journal B, 2, 20-30.",
            "Williams, C. (2018). Third article. Journal C, 3, 30-40.",
        ]
        result = parse_references(entries)

        assert len(result) == 3
        years = [r.year for r in result]
        assert 2020 in years
        assert 2019 in years
        assert 2018 in years


class TestMatchCitations:
    """Tests for citation matching."""

    def test_match_author_year(self):
        """Test matching author-year citations to references."""
        from app.models.schemas import Citation, InTextCitation

        in_text = [
            InTextCitation(
                text="(Smith, 2020)",
                start_pos=0,
                end_pos=13,
                citation_type=CitationType.AUTHOR_YEAR,
                reference_ids=["smith_2020"],
            )
        ]
        references = [
            Citation(
                id="smith_2020",
                raw_text="Smith, J. (2020). Title. Journal.",
                authors=["Smith, J."],
                year=2020,
            )
        ]

        match_result = match_citations_to_references(in_text, references)

        assert "(Smith, 2020)" in match_result.matches
        assert "smith_2020" in match_result.matches["(Smith, 2020)"]

    def test_match_numeric(self):
        """Test matching numeric citations to references."""
        from app.models.schemas import Citation, InTextCitation

        in_text = [
            InTextCitation(
                text="[1]",
                start_pos=0,
                end_pos=3,
                citation_type=CitationType.NUMERIC,
                reference_ids=["1"],
            )
        ]
        references = [
            Citation(
                id="1",
                raw_text="Smith J. Title. 2020.",
                authors=["Smith J"],
                year=2020,
            )
        ]

        match_result = match_citations_to_references(in_text, references)

        assert "[1]" in match_result.matches
        assert "1" in match_result.matches["[1]"]
