"""Tests for reference completeness checker."""

import pytest

from app.models.schemas import Citation, IssueSeverity
from app.services.completeness_checker import (
    check_reference_completeness,
    get_completeness_score,
    get_completeness_report,
)


class TestCompletenessScore:
    """Tests for completeness score calculation."""

    def test_complete_reference(self):
        """Test that a complete reference gets full score."""
        ref = Citation(
            id="test1",
            raw_text="Smith, J. (2020). Title. Journal, 10(2), 45-67.",
            authors=["Smith, J."],
            title="Complete title here",
            year=2020,
            journal="Journal of Testing",
            pages="45-67",
        )

        score = get_completeness_score(ref)

        assert score == 1.0

    def test_reference_with_doi_no_pages(self):
        """Test that DOI substitutes for missing pages."""
        ref = Citation(
            id="test2",
            raw_text="Smith, J. (2020). Title. Journal.",
            authors=["Smith, J."],
            title="Title",
            year=2020,
            journal="Journal",
            doi="10.1234/test",  # DOI instead of pages
        )

        score = get_completeness_score(ref)

        assert score == 1.0  # DOI substitutes for pages

    def test_missing_authors(self):
        """Test score for reference missing authors."""
        ref = Citation(
            id="test3",
            raw_text="(2020). Title. Journal, 10, 45-67.",
            authors=[],
            title="Title",
            year=2020,
            journal="Journal",
            pages="45-67",
        )

        score = get_completeness_score(ref)

        assert score < 1.0
        assert score == 0.75  # Missing 25% for authors

    def test_empty_reference(self):
        """Test score for mostly empty reference."""
        ref = Citation(
            id="test4",
            raw_text="Some text",
        )

        score = get_completeness_score(ref)

        assert score == 0.0


class TestBatchCompletenessCheck:
    """Tests for batch completeness checking."""

    def test_all_complete_references(self):
        """Test batch with all complete references."""
        refs = [
            Citation(
                id=f"ref{i}",
                raw_text=f"Author{i}. Title. J. 2020;10:{i}-{i+10}.",
                authors=[f"Author{i}"],
                title=f"Title {i}",
                year=2020,
                pages=f"{i}-{i+10}",
            )
            for i in range(3)
        ]

        issues = check_reference_completeness(refs, require_identifier=True)

        # No issues for complete references
        incomplete_issues = [i for i in issues if i.issue_type == "incomplete_reference"]
        assert len(incomplete_issues) == 0

    def test_mixed_completeness(self):
        """Test batch with mixed complete and incomplete references."""
        refs = [
            Citation(
                id="complete1",
                raw_text="Smith, J. (2020). Title. Journal, 10, 45-67.",
                authors=["Smith, J."],
                title="Title",
                year=2020,
                pages="45-67",
            ),
            Citation(
                id="incomplete1",
                raw_text="(2020). Title. Journal.",
                authors=[],  # Missing authors
                title="Title",
                year=2020,
            ),
            Citation(
                id="incomplete2",
                raw_text="Jones, B. Journal.",
                authors=["Jones, B."],
                # Missing title and year
            ),
        ]

        issues = check_reference_completeness(refs, require_identifier=False)

        incomplete_issues = [i for i in issues if i.issue_type == "incomplete_reference"]
        assert len(incomplete_issues) == 2

    def test_issue_severity(self):
        """Test that missing critical fields have WARNING severity."""
        refs = [
            Citation(
                id="test",
                raw_text="Smith, J.",
                authors=["Smith, J."],
                # Missing title and year
            )
        ]

        issues = check_reference_completeness(refs, require_identifier=False)

        assert len(issues) > 0
        assert all(i.severity == IssueSeverity.WARNING for i in issues)

    def test_disable_identifier_check(self):
        """Test disabling the identifier requirement."""
        refs = [
            Citation(
                id="test",
                raw_text="Smith, J. (2020). Title. Journal.",
                authors=["Smith, J."],
                title="Title",
                year=2020,
                # No pages or DOI
            )
        ]

        # With identifier required
        issues_required = check_reference_completeness(refs, require_identifier=True)

        # Without identifier required
        issues_not_required = check_reference_completeness(refs, require_identifier=False)

        assert len(issues_required) > len(issues_not_required)


class TestCompletenessReport:
    """Tests for completeness report generation."""

    def test_report_structure(self):
        """Test that report has expected structure."""
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
                raw_text="Incomplete",
                authors=["Jones"],
            ),
        ]

        report = get_completeness_report(refs)

        assert "total_references" in report
        assert "incomplete_count" in report
        assert "average_score" in report
        assert "missing_fields_count" in report
        assert "per_reference_scores" in report

    def test_report_counts(self):
        """Test that report counts are correct."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Complete ref",
                authors=["Smith"],
                title="Title",
                year=2020,
                journal="Journal",
                doi="10.1234/test",
            ),
            Citation(
                id="ref2",
                raw_text="Incomplete",
                authors=["Jones"],
                # Missing everything else
            ),
        ]

        report = get_completeness_report(refs)

        assert report["total_references"] == 2
        assert report["incomplete_count"] == 1
