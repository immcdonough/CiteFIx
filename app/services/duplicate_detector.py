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
    confidence: float
    match_type: str  # "doi_match", "title_fuzzy", "author_year"
    differences: list[str]


def detect_duplicates(references: list[Citation]) -> list[ValidationIssue]:
    """
    Detect potential duplicate references using multiple strategies.

    Strategies:
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
    processed_pairs: set[tuple[str, str]] = set()

    # Strategy 1: DOI matching (definite duplicates)
    doi_map: dict[str, list[Citation]] = {}
    for ref in references:
        if ref.doi:
            normalized_doi = ref.doi.lower().strip()
            if normalized_doi not in doi_map:
                doi_map[normalized_doi] = []
            doi_map[normalized_doi].append(ref)

    for doi, refs in doi_map.items():
        if len(refs) > 1:
            group = DuplicateGroup(
                reference_ids=[r.id for r in refs],
                confidence=1.0,
                match_type="doi_match",
                differences=_find_differences(refs),
            )
            duplicate_groups.append(group)
            # Mark these pairs as processed
            for i, r1 in enumerate(refs):
                for r2 in refs[i+1:]:
                    processed_pairs.add(_make_pair_key(r1.id, r2.id))

    # Strategy 2: Fuzzy title matching
    for i, ref1 in enumerate(references):
        for ref2 in references[i+1:]:
            pair_key = _make_pair_key(ref1.id, ref2.id)
            if pair_key in processed_pairs:
                continue

            if ref1.title and ref2.title:
                similarity = fuzz.ratio(
                    ref1.title.lower(),
                    ref2.title.lower()
                )
                if similarity >= TITLE_SIMILARITY_THRESHOLD:
                    group = DuplicateGroup(
                        reference_ids=[ref1.id, ref2.id],
                        confidence=similarity / 100.0,
                        match_type="title_fuzzy",
                        differences=_find_differences([ref1, ref2]),
                    )
                    duplicate_groups.append(group)
                    processed_pairs.add(pair_key)

    # Strategy 3: Author overlap + year match
    for i, ref1 in enumerate(references):
        for ref2 in references[i+1:]:
            pair_key = _make_pair_key(ref1.id, ref2.id)
            if pair_key in processed_pairs:
                continue

            if _has_author_year_match(ref1, ref2):
                group = DuplicateGroup(
                    reference_ids=[ref1.id, ref2.id],
                    confidence=0.7,
                    match_type="author_year",
                    differences=_find_differences([ref1, ref2]),
                )
                duplicate_groups.append(group)
                processed_pairs.add(pair_key)

    # Convert to issues
    for group in duplicate_groups:
        severity = IssueSeverity.WARNING if group.confidence >= 0.9 else IssueSeverity.INFO

        diff_text = ""
        if group.differences:
            diff_text = f" Differences: {'; '.join(group.differences)}"

        issues.append(ValidationIssue(
            issue_type="potential_duplicate",
            description=f"Possible duplicate references detected ({group.match_type}, {group.confidence:.0%} confidence){diff_text}",
            citation_text=", ".join(group.reference_ids),
            suggestion="Review and merge these references if they refer to the same paper",
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
