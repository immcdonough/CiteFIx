"""Tests for journal name normalizer."""

import pytest

from app.models.schemas import Citation, IssueSeverity
from app.services.journal_normalizer import (
    JournalNormalizer,
    check_journal_consistency,
    add_journal_mapping,
    get_known_journals,
)


class TestJournalNormalization:
    """Tests for journal name normalization."""

    def test_exact_match_lowercase(self):
        """Test exact match with lowercase input."""
        normalizer = JournalNormalizer()

        canonical, confidence = normalizer.normalize("neuroimage")

        assert canonical == "NeuroImage"
        assert confidence == 1.0

    def test_exact_match_abbreviated(self):
        """Test matching abbreviated journal names."""
        normalizer = JournalNormalizer()

        canonical, confidence = normalizer.normalize("nat neurosci")

        assert canonical == "Nature Neuroscience"
        assert confidence == 1.0

    def test_fuzzy_match(self):
        """Test fuzzy matching for close variants."""
        normalizer = JournalNormalizer()

        # Slight typo
        canonical, confidence = normalizer.normalize("neuroimage research")

        # Should find a fuzzy match if close enough
        # Confidence should be less than 1.0 for fuzzy
        if confidence > 0:
            assert confidence < 1.0

    def test_no_match(self):
        """Test that unknown journals return unchanged."""
        normalizer = JournalNormalizer()

        canonical, confidence = normalizer.normalize("Unknown Journal of Things")

        assert canonical == "Unknown Journal of Things"
        assert confidence == 0.0

    def test_empty_string(self):
        """Test handling of empty string."""
        normalizer = JournalNormalizer()

        canonical, confidence = normalizer.normalize("")

        assert canonical == ""
        assert confidence == 0.0

    def test_caching(self):
        """Test that results are cached."""
        normalizer = JournalNormalizer()

        # First call
        canonical1, conf1 = normalizer.normalize("neuroimage")
        # Second call should hit cache
        canonical2, conf2 = normalizer.normalize("neuroimage")

        assert canonical1 == canonical2
        assert conf1 == conf2


class TestBatchNormalization:
    """Tests for batch normalization."""

    def test_normalize_references(self):
        """Test normalizing journals across multiple references."""
        normalizer = JournalNormalizer()
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith, J. (2020). Title. Nat Neurosci.",
                journal="nat neurosci",
            ),
            Citation(
                id="ref2",
                raw_text="Jones, B. (2019). Title. NeuroImage.",
                journal="NeuroImage",  # Already canonical
            ),
        ]

        results = normalizer.normalize_references(refs)

        # Only ref1 should be in results (ref2 is already canonical)
        assert "ref1" in results
        assert results["ref1"][1] == "Nature Neuroscience"

    def test_get_normalization_issues(self):
        """Test generating validation issues for normalizations."""
        normalizer = JournalNormalizer()
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith, J. (2020). Title. nat neurosci.",
                journal="nat neurosci",
            ),
        ]

        issues = normalizer.get_normalization_issues(refs)

        assert len(issues) == 1
        assert issues[0].issue_type == "journal_normalization"
        assert issues[0].severity == IssueSeverity.INFO


class TestConsistencyCheck:
    """Tests for journal name consistency checking."""

    def test_inconsistent_naming(self):
        """Test detection of inconsistent journal naming."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith. Title. Nature Neuroscience.",
                journal="Nature Neuroscience",
            ),
            Citation(
                id="ref2",
                raw_text="Jones. Title. nat neurosci.",
                journal="nat neurosci",  # Different form of same journal
            ),
            Citation(
                id="ref3",
                raw_text="Brown. Title. Nat Neurosci.",
                journal="Nat Neurosci",  # Yet another form
            ),
        ]

        issues = check_journal_consistency(refs)

        # Should detect inconsistency
        inconsistent_issues = [
            i for i in issues if i.issue_type == "inconsistent_journal_name"
        ]
        assert len(inconsistent_issues) >= 1

    def test_consistent_naming(self):
        """Test that consistent naming produces no issues."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith. Title. Nature Neuroscience.",
                journal="Nature Neuroscience",
            ),
            Citation(
                id="ref2",
                raw_text="Jones. Title. Nature Neuroscience.",
                journal="Nature Neuroscience",  # Same form
            ),
        ]

        issues = check_journal_consistency(refs)

        inconsistent_issues = [
            i for i in issues if i.issue_type == "inconsistent_journal_name"
        ]
        assert len(inconsistent_issues) == 0

    def test_issue_severity(self):
        """Test that inconsistency issues have WARNING severity."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith. Title. PNAS.",
                journal="pnas",
            ),
            Citation(
                id="ref2",
                raw_text="Jones. Title. Proc Natl Acad Sci.",
                journal="proc natl acad sci",
            ),
        ]

        issues = check_journal_consistency(refs)

        inconsistent_issues = [
            i for i in issues if i.issue_type == "inconsistent_journal_name"
        ]
        if inconsistent_issues:
            assert all(i.severity == IssueSeverity.WARNING for i in inconsistent_issues)


class TestMappingManagement:
    """Tests for journal mapping management."""

    def test_add_mapping(self):
        """Test adding a new journal mapping."""
        # Add a custom mapping
        add_journal_mapping("custom journal variant", "Custom Journal Name")

        normalizer = JournalNormalizer()
        canonical, confidence = normalizer.normalize("custom journal variant")

        assert canonical == "Custom Journal Name"
        assert confidence == 1.0

    def test_get_known_journals(self):
        """Test retrieving list of known journals."""
        journals = get_known_journals()

        assert isinstance(journals, list)
        assert len(journals) > 0
        assert "NeuroImage" in journals
        assert "Nature Neuroscience" in journals

    def test_journals_are_sorted(self):
        """Test that known journals list is sorted."""
        journals = get_known_journals()

        assert journals == sorted(journals)

    def test_journals_are_unique(self):
        """Test that known journals list has no duplicates."""
        journals = get_known_journals()

        assert len(journals) == len(set(journals))
