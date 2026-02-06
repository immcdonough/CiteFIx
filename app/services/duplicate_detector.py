"""Enhanced duplicate reference detection with fuzzy matching."""

from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz

from app.models.schemas import Citation, ValidationIssue, IssueSeverity


# Thresholds for fuzzy matching
TITLE_SIMILARITY_THRESHOLD = 85  # Percentage
AUTHOR_OVERLAP_THRESHOLD = 0.6   # Fraction


@dataclass
class DuplicateGroup:
    """A group of potentially duplicate references."""
    reference_ids: list[str]
    reference_indices: list[int]  # Position in reference list (1-indexed for display)
    confidence: float
    match_type: str  # "doi_match", "title_fuzzy", "author_year", "exact_duplicate"
    differences: list[str]
    raw_text_snippet: str = ""  # First reference's text for context


def detect_duplicates(references: list[Citation]) -> list[ValidationIssue]:
    """
    Detect potential duplicate references using multiple strategies.

    Strategies:
    0. Exact text match (identical references)
    1. Exact DOI match (highest confidence)
    2. Fuzzy title matching (rapidfuzz)
    3. Author overlap + similar year

    Args:
        references: List of Citation objects

    Returns:
        List of ValidationIssue for potential duplicates
    """
    issues = []
    duplicate_groups: list[DuplicateGroup] = []
    processed_pairs: set[tuple[int, int]] = set()  # Use indices, not IDs

    # Build index map for quick lookup
    ref_indices = {i: ref for i, ref in enumerate(references)}

    # Strategy 0: Exact text duplicates (same raw_text)
    text_map: dict[str, list[int]] = {}  # raw_text -> list of indices
    for i, ref in enumerate(references):
        if ref.raw_text:
            normalized_text = ref.raw_text.strip().lower()
            if normalized_text not in text_map:
                text_map[normalized_text] = []
            text_map[normalized_text].append(i)

    for text, indices in text_map.items():
        if len(indices) > 1:
            refs = [references[i] for i in indices]
            group = DuplicateGroup(
                reference_ids=[r.id for r in refs],
                reference_indices=[i + 1 for i in indices],  # 1-indexed for display
                confidence=1.0,
                match_type="exact_duplicate",
                differences=[],
                raw_text_snippet=refs[0].raw_text[:80] if refs[0].raw_text else "",
            )
            duplicate_groups.append(group)
            # Mark these pairs as processed
            for i, idx1 in enumerate(indices):
                for idx2 in indices[i+1:]:
                    processed_pairs.add(_make_index_pair(idx1, idx2))

    # Strategy 1: DOI matching (definite duplicates)
    doi_map: dict[str, list[int]] = {}  # doi -> list of indices
    for i, ref in enumerate(references):
        if ref.doi:
            normalized_doi = ref.doi.lower().strip()
            if normalized_doi not in doi_map:
                doi_map[normalized_doi] = []
            doi_map[normalized_doi].append(i)

    for doi, indices in doi_map.items():
        if len(indices) > 1:
            # Check if already processed as exact duplicate
            if _make_index_pair(indices[0], indices[1]) in processed_pairs:
                continue
            refs = [references[i] for i in indices]
            group = DuplicateGroup(
                reference_ids=[r.id for r in refs],
                reference_indices=[i + 1 for i in indices],
                confidence=1.0,
                match_type="doi_match",
                differences=_find_differences(refs),
                raw_text_snippet=refs[0].raw_text[:80] if refs[0].raw_text else "",
            )
            duplicate_groups.append(group)
            for i, idx1 in enumerate(indices):
                for idx2 in indices[i+1:]:
                    processed_pairs.add(_make_index_pair(idx1, idx2))

    # Strategy 2: Fuzzy title matching
    for i, ref1 in enumerate(references):
        for j, ref2 in enumerate(references[i+1:], start=i+1):
            if _make_index_pair(i, j) in processed_pairs:
                continue

            if ref1.title and ref2.title:
                similarity = fuzz.ratio(
                    ref1.title.lower(),
                    ref2.title.lower()
                )
                if similarity >= TITLE_SIMILARITY_THRESHOLD:
                    group = DuplicateGroup(
                        reference_ids=[ref1.id, ref2.id],
                        reference_indices=[i + 1, j + 1],
                        confidence=similarity / 100.0,
                        match_type="title_fuzzy",
                        differences=_find_differences([ref1, ref2]),
                        raw_text_snippet=ref1.raw_text[:80] if ref1.raw_text else "",
                    )
                    duplicate_groups.append(group)
                    processed_pairs.add(_make_index_pair(i, j))

    # Strategy 3: Author overlap + year match
    for i, ref1 in enumerate(references):
        for j, ref2 in enumerate(references[i+1:], start=i+1):
            if _make_index_pair(i, j) in processed_pairs:
                continue

            if _has_author_year_match(ref1, ref2):
                group = DuplicateGroup(
                    reference_ids=[ref1.id, ref2.id],
                    reference_indices=[i + 1, j + 1],
                    confidence=0.7,
                    match_type="author_year",
                    differences=_find_differences([ref1, ref2]),
                    raw_text_snippet=ref1.raw_text[:80] if ref1.raw_text else "",
                )
                duplicate_groups.append(group)
                processed_pairs.add(_make_index_pair(i, j))

    # Convert to issues
    for group in duplicate_groups:
        severity = IssueSeverity.WARNING if group.confidence >= 0.9 else IssueSeverity.INFO

        # Build description based on match type
        if group.match_type == "exact_duplicate":
            description = "Identical reference appears multiple times in reference list"
        else:
            diff_text = ""
            if group.differences:
                diff_text = f" Differences: {'; '.join(group.differences)}"
            description = f"Possible duplicate references ({group.match_type}, {group.confidence:.0%} confidence){diff_text}"

        # Show positions for clarity (especially when IDs are the same)
        positions = ", ".join(f"#{i}" for i in group.reference_indices)

        # Use snippet for citation_text if IDs are identical
        unique_ids = set(group.reference_ids)
        if len(unique_ids) == 1:
            # All IDs are the same - show positions and snippet
            citation_text = f"Refs {positions}: {group.raw_text_snippet}..."
        else:
            citation_text = f"Refs {positions} ({', '.join(group.reference_ids)})"

        issues.append(ValidationIssue(
            issue_type="potential_duplicate",
            description=description,
            citation_text=citation_text,
            suggestion="Remove the duplicate entry from your reference list",
            severity=severity,
            related_references=group.reference_ids,
        ))

    return issues


def _has_author_year_match(ref1: Citation, ref2: Citation) -> bool:
    """Check if two references have overlapping authors and same/similar year."""
    # Year must match or be within 1 year
    if ref1.year and ref2.year:
        if abs(ref1.year - ref2.year) > 1:
            return False
    elif ref1.year or ref2.year:
        # One has year, one doesn't - can't match on year
        return False

    # Check author overlap
    if not ref1.authors or not ref2.authors:
        return False

    authors1 = {_normalize_author(a) for a in ref1.authors}
    authors2 = {_normalize_author(a) for a in ref2.authors}

    overlap = len(authors1 & authors2)
    total = max(len(authors1), len(authors2))

    if total == 0:
        return False

    return overlap / total >= AUTHOR_OVERLAP_THRESHOLD


def _normalize_author(author: str) -> str:
    """Normalize author name for comparison."""
    author = author.lower().strip()
    # Extract last name only
    if "," in author:
        return author.split(",")[0].strip()
    parts = author.split()
    # Return last word (likely last name)
    return parts[-1] if parts else author


def _make_pair_key(id1: str, id2: str) -> tuple[str, str]:
    """Create a consistent key for a pair of reference IDs."""
    return tuple(sorted([id1, id2]))


def _make_index_pair(idx1: int, idx2: int) -> tuple[int, int]:
    """Create a consistent key for a pair of reference indices."""
    return (min(idx1, idx2), max(idx1, idx2))


def _find_differences(refs: list[Citation]) -> list[str]:
    """Find differences between potential duplicate references."""
    differences = []

    # Check author formatting differences
    author_strs = [", ".join(r.authors) if r.authors else "" for r in refs]
    if len(set(author_strs)) > 1:
        differences.append("author formatting")

    # Check year differences
    years = [r.year for r in refs if r.year]
    if len(set(years)) > 1:
        differences.append(f"years differ ({', '.join(str(y) for y in years)})")

    # Check title differences
    titles = [r.title for r in refs if r.title]
    if len(titles) > 1 and len(set(t.lower() for t in titles)) > 1:
        differences.append("titles differ slightly")

    # Check journal differences
    journals = [r.journal for r in refs if r.journal]
    if len(set(j.lower() if j else "" for j in journals)) > 1:
        differences.append("journal names differ")

    # Check DOI differences (one has, one doesn't)
    dois = [r.doi for r in refs]
    if any(dois) and not all(dois):
        differences.append("only some have DOI")

    return differences


def merge_duplicates(refs: list[Citation]) -> Citation:
    """
    Merge duplicate references into a single reference.

    Prefers:
    - Reference with DOI
    - Reference with more complete information
    - First reference as fallback

    Args:
        refs: List of duplicate Citation objects

    Returns:
        Merged Citation
    """
    if not refs:
        raise ValueError("Cannot merge empty list")
    if len(refs) == 1:
        return refs[0]

    # Sort by completeness (prefer refs with DOI, then most fields)
    def completeness_score(ref: Citation) -> tuple[int, int]:
        has_doi = 1 if ref.doi else 0
        field_count = sum([
            bool(ref.authors),
            bool(ref.year),
            bool(ref.title),
            bool(ref.journal),
            bool(ref.volume),
            bool(ref.pages),
        ])
        return (has_doi, field_count)

    sorted_refs = sorted(refs, key=completeness_score, reverse=True)
    best = sorted_refs[0]

    # Merge missing fields from other refs
    for ref in sorted_refs[1:]:
        if not best.doi and ref.doi:
            best.doi = ref.doi
            best.doi_url = ref.doi_url
        if not best.pages and ref.pages:
            best.pages = ref.pages
        if not best.volume and ref.volume:
            best.volume = ref.volume
        if not best.issue and ref.issue:
            best.issue = ref.issue
        if not best.journal and ref.journal:
            best.journal = ref.journal

    return best
