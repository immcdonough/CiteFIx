"""Tests for citation validation service."""

import pytest

from app.models.schemas import Citation, CitationType, InTextCitation
from app.services.validator import (
    validate_citations,
    generate_validation_summary,
)


class TestValidateCitations:
    """Tests for validate_citations function."""

    def test_valid_document(self):
        """Test validation of document with matching citations."""
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

        report = validate_citations(in_text, references)

        assert report.is_valid
        assert report.total_in_text_citations == 1
        assert report.total_references == 1
        assert len(report.issues) == 0

    def test_missing_reference(self):
        """Test detection of citation without matching reference."""
        in_text = [
            InTextCitation(
                text="(Jones, 2021)",
                start_pos=0,
                end_pos=13,
                citation_type=CitationType.AUTHOR_YEAR,
                reference_ids=["jones_2021"],
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

        report = validate_citations(in_text, references)

        assert not report.is_valid
        assert len(report.issues) >= 1

        issue_types = [i.issue_type for i in report.issues]
        assert "missing_reference" in issue_types

    def test_uncited_reference(self):
        """Test detection of reference not cited in text."""
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
            ),
            Citation(
                id="jones_2019",
                raw_text="Jones, B. (2019). Other. Journal.",
                authors=["Jones, B."],
                year=2019,
            ),
        ]

        report = validate_citations(in_text, references)

        assert not report.is_valid
        issue_types = [i.issue_type for i in report.issues]
        assert "uncited_reference" in issue_types

    def test_duplicate_references(self):
        """Test detection of duplicate references."""
        in_text: list[InTextCitation] = []
        references = [
            Citation(
                id="smith_2020_a",
                raw_text="Smith, J. (2020). Same title. Journal.",
                authors=["Smith, J."],
                title="Same title",
                year=2020,
            ),
            Citation(
                id="smith_2020_b",
                raw_text="Smith, J. (2020). Same title. Journal.",
                authors=["Smith, J."],
                title="Same title",
                year=2020,
            ),
        ]

        report = validate_citations(in_text, references)

        issue_types = [i.issue_type for i in report.issues]
        assert "duplicate_reference" in issue_types


class TestValidationSummary:
    """Tests for validation summary generation."""

    def test_summary_valid(self):
        """Test summary for valid document."""
        from app.models.schemas import ValidationReport

        report = ValidationReport(
            total_in_text_citations=5,
            total_references=5,
            matched_citations=5,
            issues=[],
            is_valid=True,
        )

        summary = generate_validation_summary(report)

        assert "VALID" in summary
        assert "5" in summary

    def test_summary_with_issues(self):
        """Test summary with issues."""
        from app.models.schemas import ValidationIssue, ValidationReport

        report = ValidationReport(
            total_in_text_citations=3,
            total_references=2,
            matched_citations=2,
            issues=[
                ValidationIssue(
                    issue_type="missing_reference",
                    description="Citation not found",
                    citation_text="(Unknown, 2020)",
                )
            ],
            is_valid=False,
        )

        summary = generate_validation_summary(report)

        assert "ISSUES FOUND" in summary
        assert "missing_reference" in summary.lower() or "MISSING" in summary
