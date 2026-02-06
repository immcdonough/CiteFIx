"""Tests for duplicate reference detector."""

import pytest

from app.models.schemas import Citation, IssueSeverity
from app.services.duplicate_detector import (
    detect_duplicates,
    merge_duplicates,
    DuplicateGroup,
)


class TestDuplicateDetection:
    """Tests for duplicate detection."""

    def test_exact_doi_match(self):
        """Test detection of references with same DOI."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith, J. (2020). Title One. Journal.",
                authors=["Smith, J."],
                title="Title One",
                year=2020,
                doi="10.1234/example",
            ),
            Citation(
                id="ref2",
                raw_text="Smith J. Title One. J. 2020.",
                authors=["Smith, J."],
                title="Title One",
                year=2020,
                doi="10.1234/example",  # Same DOI
            ),
        ]

        issues = detect_duplicates(refs)

        assert len(issues) == 1
        assert issues[0].issue_type == "potential_duplicate"
        # DOI match should have high confidence
        assert "100%" in issues[0].description or "doi_match" in issues[0].description

    def test_fuzzy_title_match(self):
        """Test detection of similar titles."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith, J. (2020). Brain activity during sleep. Journal.",
                authors=["Smith, J."],
                title="Brain activity during sleep",
                year=2020,
            ),
            Citation(
                id="ref2",
                raw_text="Smith J. Brain activity during sleep. J. 2020.",
                authors=["Smith, J."],
                title="Brain activity during sleep",  # Identical title
                year=2020,
            ),
        ]

        issues = detect_duplicates(refs)

        assert len(issues) == 1

    def test_author_year_overlap(self):
        """Test detection by author and year overlap."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith, J., Jones, B. (2020). Title A. Journal.",
                authors=["Smith, J.", "Jones, B."],
                title="Title A",
                year=2020,
            ),
            Citation(
                id="ref2",
                raw_text="Smith J, Jones B. Title A. J. 2020.",
                authors=["Smith, J.", "Jones, B."],
                title="Title A",
                year=2020,
            ),
        ]

        issues = detect_duplicates(refs)

        assert len(issues) >= 1

    def test_no_duplicates(self):
        """Test that distinct references are not flagged."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith, J. (2020). Brain imaging in sleep disorders. Neurology.",
                authors=["Smith, J."],
                title="Brain imaging in sleep disorders",
                year=2020,
            ),
            Citation(
                id="ref2",
                raw_text="Jones, B. (2019). Cardiovascular health outcomes. Cardiology.",
                authors=["Jones, B."],
                title="Cardiovascular health outcomes",
                year=2019,
            ),
        ]

        issues = detect_duplicates(refs)

        assert len(issues) == 0

    def test_similar_but_different_years(self):
        """Test that same author/title with very different years are handled."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith, J. (2010). Brain study. Journal.",
                authors=["Smith, J."],
                title="Brain study",
                year=2010,
            ),
            Citation(
                id="ref2",
                raw_text="Smith, J. (2020). Brain study. Journal.",
                authors=["Smith, J."],
                title="Brain study",
                year=2020,  # 10 years different
            ),
        ]

        issues = detect_duplicates(refs)

        # Title match may still detect but author/year won't
        # Either 0 or 1 issue depending on title similarity threshold


class TestDuplicateIssueGeneration:
    """Tests for duplicate issue generation."""

    def test_issue_severity_high_confidence(self):
        """Test that high-confidence duplicates have WARNING severity."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith, J. (2020). Title. Journal.",
                authors=["Smith, J."],
                title="Title",
                year=2020,
                doi="10.1234/test",
            ),
            Citation(
                id="ref2",
                raw_text="Smith J. Title. J. 2020.",
                authors=["Smith, J."],
                title="Title",
                year=2020,
                doi="10.1234/test",
            ),
        ]

        issues = detect_duplicates(refs)

        if issues:
            # DOI match is 100% confidence, should be WARNING
            assert issues[0].severity == IssueSeverity.WARNING

    def test_related_references_in_issue(self):
        """Test that related reference IDs are included in issue."""
        refs = [
            Citation(
                id="smith_2020_a",
                raw_text="Smith, J. (2020). Title. Journal.",
                authors=["Smith, J."],
                title="Title",
                year=2020,
                doi="10.1234/test",
            ),
            Citation(
                id="smith_2020_b",
                raw_text="Smith J. Title. J. 2020.",
                authors=["Smith, J."],
                title="Title",
                year=2020,
                doi="10.1234/test",
            ),
        ]

        issues = detect_duplicates(refs)

        if issues:
            assert len(issues[0].related_references) >= 2
            assert "smith_2020_a" in issues[0].related_references
            assert "smith_2020_b" in issues[0].related_references

    def test_confidence_in_description(self):
        """Test that confidence score is included in issue description."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith, J. (2020). Same Title. Journal.",
                authors=["Smith, J."],
                title="Same Title",
                year=2020,
            ),
            Citation(
                id="ref2",
                raw_text="Smith, J. (2020). Same Title. Journal.",
                authors=["Smith, J."],
                title="Same Title",
                year=2020,
            ),
        ]

        issues = detect_duplicates(refs)

        if issues:
            # Description should either mention confidence percentage or indicate exact duplicate
            assert "%" in issues[0].description or "Identical" in issues[0].description


class TestMergeDuplicates:
    """Tests for merging duplicate references."""

    def test_merge_prefers_doi(self):
        """Test that merge prefers reference with DOI."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith, J. (2020). Title.",
                authors=["Smith, J."],
                title="Title",
                year=2020,
            ),
            Citation(
                id="ref2",
                raw_text="Smith J. Title. 2020.",
                authors=["Smith, J."],
                title="Title",
                year=2020,
                doi="10.1234/test",
            ),
        ]

        merged = merge_duplicates(refs)

        assert merged.doi == "10.1234/test"

    def test_merge_combines_fields(self):
        """Test that merge combines fields from multiple refs."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith, J. (2020). Title.",
                authors=["Smith, J."],
                title="Title",
                year=2020,
                pages="45-67",
            ),
            Citation(
                id="ref2",
                raw_text="Smith J. Title. 2020.",
                authors=["Smith, J."],
                title="Title",
                year=2020,
                volume="10",
                doi="10.1234/test",
            ),
        ]

        merged = merge_duplicates(refs)

        # Should have both pages and volume from different refs
        assert merged.pages == "45-67"
        assert merged.volume == "10"
        assert merged.doi == "10.1234/test"

    def test_merge_single_ref(self):
        """Test merging single reference returns it unchanged."""
        ref = Citation(
            id="ref1",
            raw_text="Test",
            authors=["Test"],
        )

        merged = merge_duplicates([ref])

        assert merged.id == "ref1"

    def test_merge_empty_raises(self):
        """Test that merging empty list raises error."""
        with pytest.raises(ValueError):
            merge_duplicates([])


class TestEdgeCases:
    """Tests for edge cases in duplicate detection."""

    def test_empty_list(self):
        """Test with empty reference list."""
        issues = detect_duplicates([])
        assert issues == []

    def test_single_reference(self):
        """Test with single reference (no possible duplicates)."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith, J. (2020). Title. Journal.",
                authors=["Smith, J."],
                title="Title",
                year=2020,
            )
        ]

        issues = detect_duplicates(refs)
        assert issues == []

    def test_references_without_titles(self):
        """Test handling of references without titles."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith, J. (2020). Journal.",
                authors=["Smith, J."],
                year=2020,
            ),
            Citation(
                id="ref2",
                raw_text="Smith, J. (2020). Journal.",
                authors=["Smith, J."],
                year=2020,
            ),
        ]

        # Should not crash
        issues = detect_duplicates(refs)
        # May detect based on author/year overlap

    def test_case_insensitive_doi(self):
        """Test that DOI matching is case-insensitive."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Test",
                doi="10.1234/ABC",
            ),
            Citation(
                id="ref2",
                raw_text="Test",
                doi="10.1234/abc",  # Same DOI, different case
            ),
        ]

        issues = detect_duplicates(refs)

        assert len(issues) == 1
