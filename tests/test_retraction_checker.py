"""Tests for retraction checker."""

import pytest
from unittest.mock import Mock, patch

from app.models.schemas import Citation, IssueSeverity
from app.services.retraction_checker import (
    RetractionChecker,
    RetractionStatus,
)


class TestRetractionStatus:
    """Tests for RetractionStatus dataclass."""

    def test_basic_status(self):
        """Test creating basic retraction status."""
        status = RetractionStatus(
            reference_id="ref1",
            doi="10.1234/test",
            is_retracted=False,
        )

        assert status.reference_id == "ref1"
        assert status.doi == "10.1234/test"
        assert status.is_retracted is False
        assert status.retraction_date is None
        assert status.error is None

    def test_retracted_status(self):
        """Test retracted paper status."""
        status = RetractionStatus(
            reference_id="ref1",
            doi="10.1234/retracted",
            is_retracted=True,
            retraction_date="2021-01-15",
            retraction_reason="Data fabrication",
            retraction_notice_doi="10.1234/retraction",
        )

        assert status.is_retracted is True
        assert status.retraction_date == "2021-01-15"
        assert status.retraction_notice_doi == "10.1234/retraction"


class TestRetractionChecker:
    """Tests for RetractionChecker class."""

    def test_no_doi_returns_none(self):
        """Test that reference without DOI returns None."""
        checker = RetractionChecker()
        ref = Citation(
            id="ref1",
            raw_text="Smith, J. (2020). Title. Journal.",
            authors=["Smith, J."],
            year=2020,
        )

        result = checker.check_reference(ref)

        assert result is None

    def test_caching(self):
        """Test that results are cached."""
        checker = RetractionChecker()

        # Mock the _query_crossref method
        with patch.object(checker, '_query_crossref') as mock_query:
            mock_query.return_value = RetractionStatus(
                reference_id="ref1",
                doi="10.1234/test",
                is_retracted=False,
            )

            ref = Citation(
                id="ref1",
                raw_text="Test",
                doi="10.1234/test",
            )

            # First call
            result1 = checker.check_reference(ref)
            # Second call should use cache
            result2 = checker.check_reference(ref)

            # _query_crossref should only be called once
            assert mock_query.call_count == 1

    def test_doi_normalization(self):
        """Test that DOIs are normalized before caching."""
        checker = RetractionChecker()

        with patch.object(checker, '_query_crossref') as mock_query:
            mock_query.return_value = RetractionStatus(
                reference_id="ref1",
                doi="10.1234/test",
                is_retracted=False,
            )

            ref1 = Citation(id="ref1", raw_text="", doi="10.1234/TEST")
            ref2 = Citation(id="ref2", raw_text="", doi="10.1234/test")

            checker.check_reference(ref1)
            checker.check_reference(ref2)

            # Should only query once due to case-insensitive normalization
            assert mock_query.call_count == 1


class TestBatchChecking:
    """Tests for batch retraction checking."""

    def test_filters_by_doi(self):
        """Test that only references with DOI are checked."""
        checker = RetractionChecker()

        refs = [
            Citation(id="ref1", raw_text="", doi="10.1234/a"),
            Citation(id="ref2", raw_text=""),  # No DOI
            Citation(id="ref3", raw_text="", doi="10.1234/b"),
        ]

        with patch.object(checker, '_query_crossref') as mock_query:
            mock_query.return_value = RetractionStatus(
                reference_id="",
                doi="",
                is_retracted=False,
            )

            checker.check_references(refs)

            # Should only check 2 references (those with DOI)
            assert mock_query.call_count == 2

    def test_retraction_issue_generation(self):
        """Test that issues are generated for retracted papers."""
        checker = RetractionChecker()

        refs = [
            Citation(
                id="ref1",
                raw_text="Smith, J. (2020). Retracted paper. Journal.",
                authors=["Smith, J."],
                doi="10.1234/retracted",
            )
        ]

        with patch.object(checker, '_query_crossref') as mock_query:
            mock_query.return_value = RetractionStatus(
                reference_id="ref1",
                doi="10.1234/retracted",
                is_retracted=True,
                retraction_date="2021-01-15",
            )

            issues = checker.check_references(refs)

            assert len(issues) == 1
            assert issues[0].issue_type == "retracted_reference"
            assert issues[0].severity == IssueSeverity.ERROR

    def test_no_issues_for_clean_papers(self):
        """Test that no issues are generated for non-retracted papers."""
        checker = RetractionChecker()

        refs = [
            Citation(
                id="ref1",
                raw_text="",
                doi="10.1234/clean",
            )
        ]

        with patch.object(checker, '_query_crossref') as mock_query:
            mock_query.return_value = RetractionStatus(
                reference_id="ref1",
                doi="10.1234/clean",
                is_retracted=False,
            )

            issues = checker.check_references(refs)

            assert len(issues) == 0


class TestRetractionStats:
    """Tests for retraction statistics."""

    def test_stats_calculation(self):
        """Test statistics calculation."""
        checker = RetractionChecker()

        refs = [
            Citation(id="ref1", raw_text="", doi="10.1234/a"),
            Citation(id="ref2", raw_text=""),  # No DOI
            Citation(id="ref3", raw_text="", doi="10.1234/b"),
        ]

        with patch.object(checker, '_query_crossref') as mock_query:
            def side_effect(doi, ref_id):
                if "a" in doi:
                    return RetractionStatus(
                        reference_id=ref_id,
                        doi=doi,
                        is_retracted=True,
                    )
                return RetractionStatus(
                    reference_id=ref_id,
                    doi=doi,
                    is_retracted=False,
                )

            mock_query.side_effect = side_effect

            stats = checker.get_retraction_stats(refs)

            assert stats["total_references"] == 3
            assert stats["with_doi"] == 2
            assert stats["without_doi"] == 1
            assert stats["retracted_count"] == 1
            assert "ref1" in stats["retracted_ids"]


class TestDOICleaning:
    """Tests for DOI URL cleaning."""

    def test_https_doi_url_works(self):
        """Test that HTTPS DOI URLs are handled correctly."""
        checker = RetractionChecker()

        with patch.object(checker, '_query_crossref') as mock_query:
            mock_query.return_value = RetractionStatus(
                reference_id="ref1",
                doi="10.1234/test",
                is_retracted=False,
            )

            ref = Citation(
                id="ref1",
                raw_text="",
                doi="https://doi.org/10.1234/test",
            )

            result = checker.check_reference(ref)

            # Should return a valid result
            assert result is not None
            assert result.is_retracted is False
            # Query should be called
            assert mock_query.call_count == 1

    def test_http_doi_url_works(self):
        """Test that HTTP DOI URLs are handled correctly."""
        checker = RetractionChecker()

        with patch.object(checker, '_query_crossref') as mock_query:
            mock_query.return_value = RetractionStatus(
                reference_id="ref1",
                doi="10.1234/another",
                is_retracted=False,
            )

            ref = Citation(
                id="ref1",
                raw_text="",
                doi="http://doi.org/10.1234/another",
            )

            result = checker.check_reference(ref)

            # Should return a valid result
            assert result is not None
            assert result.is_retracted is False
            assert mock_query.call_count == 1


# Integration tests (marked to skip by default as they require network)
@pytest.mark.skip(reason="Requires network access to CrossRef API")
class TestRetractionCheckerIntegration:
    """Integration tests for retraction checker."""

    def test_known_retracted_paper(self):
        """Test checking a known retracted paper."""
        checker = RetractionChecker()

        # This is a famous retracted paper (Wakefield MMR paper)
        ref = Citation(
            id="wakefield",
            raw_text="",
            doi="10.1016/S0140-6736(97)11096-0",
        )

        status = checker.check_reference(ref)

        # Note: This may or may not show as retracted depending on CrossRef data
        assert status is not None
        assert status.doi is not None

    def test_known_valid_paper(self):
        """Test checking a known valid paper."""
        checker = RetractionChecker(email="test@example.com")

        ref = Citation(
            id="valid",
            raw_text="",
            doi="10.1038/nature12373",  # A well-cited Nature paper
        )

        status = checker.check_reference(ref)

        assert status is not None
        # Should not be retracted
        assert status.is_retracted is False or status.error is not None
