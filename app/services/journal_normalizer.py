"""Journal name normalization service."""

import json
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz, process

from app.models.schemas import Citation, ValidationIssue, IssueSeverity


# Load journal mappings
DATA_DIR = Path(__file__).parent.parent / "data"
JOURNAL_MAPPINGS: dict[str, str] = {}


def _load_mappings():
    """Load journal name mappings from JSON file."""
    global JOURNAL_MAPPINGS
    mapping_file = DATA_DIR / "journal_mappings.json"
    if mapping_file.exists():
        with open(mapping_file, encoding="utf-8") as f:
            JOURNAL_MAPPINGS = json.load(f)


# Load mappings on module import
_load_mappings()


def _is_valid_fuzzy_match(query: str, candidate: str) -> bool:
    """
    Check if a fuzzy match is valid by ensuring all significant words in the
    query are represented in the candidate.

    This prevents false matches like:
    - "Sleep Med Clin" matching "Sleep Med" (Clin is not represented)
    - "Mol Psychiatry" matching "Biol Psychiatry" (Mol doesn't match Biol)

    Args:
        query: The input journal name (normalized to lowercase)
        candidate: The candidate mapping key (normalized to lowercase)

    Returns:
        True if the match is valid, False otherwise
    """
    # Tokenize
    query_words = query.lower().split()
    candidate_words = candidate.lower().split()

    # Filter out very short tokens (1-2 chars) as they're often noise
    query_words = [w for w in query_words if len(w) >= 3]
    candidate_words = [w for w in candidate_words if len(w) >= 3]

    if not query_words:
        return True  # No significant words to check

    # Each significant word in the query must match something in the candidate
    for qword in query_words:
        word_matched = False

        for cword in candidate_words:
            # Exact match
            if qword == cword:
                word_matched = True
                break

            # Prefix/substring match (e.g., "med" in "medicine", "psychiat" in "psychiatry")
            if len(qword) >= 3 and len(cword) >= 3:
                if qword.startswith(cword) or cword.startswith(qword):
                    word_matched = True
                    break

            # High fuzzy match for typos (e.g., "psychaitry" -> "psychiatry")
            # But require very high similarity (90%) to avoid "mol" matching "biol"
            if fuzz.ratio(qword, cword) >= 90:
                word_matched = True
                break

        if not word_matched:
            # Query has a word with no match in candidate - likely different journal
            return False

    return True


class JournalNormalizer:
    """Normalize journal names to canonical forms."""

    def __init__(self, use_crossref: bool = False):
        """
        Initialize the normalizer.

        Args:
            use_crossref: Whether to query CrossRef for unknown journals
        """
        self.use_crossref = use_crossref
        self._cache: dict[str, tuple[str, float]] = {}

    def normalize(self, journal_name: str) -> tuple[str, float]:
        """
        Normalize a journal name.

        Args:
            journal_name: Original journal name

        Returns:
            Tuple of (canonical_name, confidence)
            confidence is 1.0 for exact match, <1.0 for fuzzy match, 0.0 for no match
        """
        if not journal_name:
            return journal_name, 0.0

        # Check cache
        if journal_name in self._cache:
            return self._cache[journal_name]

        # Try exact mapping (case-insensitive)
        normalized = journal_name.lower().strip()
        if normalized in JOURNAL_MAPPINGS:
            canonical = JOURNAL_MAPPINGS[normalized]
            self._cache[journal_name] = (canonical, 1.0)
            return canonical, 1.0

        # Try fuzzy matching against known journals
        # Use multiple validation layers:
        # 1. High similarity threshold (90%)
        # 2. Word-level validation to prevent false matches
        if JOURNAL_MAPPINGS:
            # Get top matches to check
            matches = process.extract(
                normalized,
                JOURNAL_MAPPINGS.keys(),
                scorer=fuzz.ratio,
                limit=5,
            )

            for match_key, score, _ in matches:
                if score < 90:
                    break  # No more good candidates

                # Validate that all words in query are represented in match
                if _is_valid_fuzzy_match(normalized, match_key):
                    canonical = JOURNAL_MAPPINGS[match_key]
                    confidence = score / 100.0
                    self._cache[journal_name] = (canonical, confidence)
                    return canonical, confidence

        # No match found
        self._cache[journal_name] = (journal_name, 0.0)
        return journal_name, 0.0

    def normalize_references(
        self,
        references: list[Citation],
    ) -> dict[str, tuple[str, str, float]]:
        """
        Normalize journal names in a list of references.

        Args:
            references: List of Citation objects

        Returns:
            Dict mapping ref_id to (original, canonical, confidence)
            Only includes references where normalization changed the name
        """
        results = {}

        for ref in references:
            if ref.journal:
                canonical, confidence = self.normalize(ref.journal)
                # Only include if name changed and we have some confidence
                if canonical.lower() != ref.journal.lower() and confidence > 0:
                    results[ref.id] = (ref.journal, canonical, confidence)

        return results

    def get_normalization_issues(
        self,
        references: list[Citation],
    ) -> list[ValidationIssue]:
        """
        Generate validation issues for journal name normalizations.

        Args:
            references: List of Citation objects

        Returns:
            List of ValidationIssue for suggested normalizations
        """
        issues = []
        normalizations = self.normalize_references(references)

        for ref_id, (original, canonical, confidence) in normalizations.items():
            severity = IssueSeverity.INFO

            issues.append(ValidationIssue(
                issue_type="journal_normalization",
                description=f"Journal name can be standardized",
                citation_text=f"{ref_id}: '{original}'",
                suggestion=f"Consider using canonical name: '{canonical}' (confidence: {confidence:.0%})",
                severity=severity,
            ))

        return issues


def check_journal_consistency(references: list[Citation]) -> list[ValidationIssue]:
    """
    Check for inconsistent journal naming across references.

    Finds cases where the same journal is referenced with different names.

    Args:
        references: List of Citation objects

    Returns:
        List of ValidationIssue for inconsistent naming
    """
    issues = []
    normalizer = JournalNormalizer()

    # Group references by normalized journal name
    journal_groups: dict[str, list[tuple[str, str]]] = {}  # canonical -> [(ref_id, original)]

    for ref in references:
        if ref.journal:
            canonical, confidence = normalizer.normalize(ref.journal)
            if confidence > 0:
                key = canonical.lower()
                if key not in journal_groups:
                    journal_groups[key] = []
                journal_groups[key].append((ref.id, ref.journal))

    # Find groups with inconsistent naming
    for canonical_key, ref_list in journal_groups.items():
        # Get unique original names
        original_names = set(name for _, name in ref_list)

        if len(original_names) > 1:
            ref_ids = [ref_id for ref_id, _ in ref_list]
            names_str = ", ".join(f"'{n}'" for n in sorted(original_names))

            issues.append(ValidationIssue(
                issue_type="inconsistent_journal_name",
                description=f"Same journal referenced with different names: {names_str}",
                citation_text=", ".join(ref_ids),
                suggestion=f"Standardize to: '{JOURNAL_MAPPINGS.get(canonical_key, list(original_names)[0])}'",
                severity=IssueSeverity.WARNING,
                related_references=ref_ids,
            ))

    return issues


def add_journal_mapping(variant: str, canonical: str) -> None:
    """
    Add a new journal name mapping.

    Args:
        variant: The variant name (will be lowercased)
        canonical: The canonical name
    """
    JOURNAL_MAPPINGS[variant.lower()] = canonical


def get_known_journals() -> list[str]:
    """Get list of all known canonical journal names."""
    return sorted(set(JOURNAL_MAPPINGS.values()))
