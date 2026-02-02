"""Reference completeness validation service."""

from app.models.schemas import Citation, ValidationIssue, IssueSeverity


def check_reference_completeness(
    references: list[Citation],
    require_identifier: bool = True,
) -> list[ValidationIssue]:
    """
    Check each reference for missing critical fields.

    Args:
        references: List of parsed references
        require_identifier: Whether to require DOI or page numbers

    Returns:
        List of ValidationIssue for incomplete references
    """
    issues = []

    for ref in references:
        missing = []

        # Check basic required fields
        if not ref.authors:
            missing.append("authors")
        if not ref.year:
            missing.append("year")
        if not ref.title:
            missing.append("title")

        # Check for identifier (DOI or pages)
        has_identifier = bool(ref.doi or ref.pages)
        if require_identifier and not has_identifier:
            missing.append("pages or DOI")

        # Check for journal (for journal articles)
        # Only flag if we have volume/issue but no journal
        if (ref.volume or ref.issue) and not ref.journal:
            missing.append("journal")

        if missing:
            # Determine severity based on what's missing
            if "authors" in missing or "year" in missing or "title" in missing:
                severity = IssueSeverity.WARNING
            else:
                severity = IssueSeverity.INFO

            issues.append(ValidationIssue(
                issue_type="incomplete_reference",
                description=f"Reference missing: {', '.join(missing)}",
                citation_text=_truncate(ref.raw_text, 100),
                suggestion=f"Add missing fields: {', '.join(missing)}",
                severity=severity,
            ))

    return issues


def get_completeness_score(ref: Citation) -> float:
    """
    Calculate a completeness score for a reference (0.0 to 1.0).

    Weights:
    - authors: 25%
    - year: 20%
    - title: 25%
    - journal: 15%
    - identifier (DOI or pages): 15%
    """
    score = 0.0

    if ref.authors:
        score += 0.25
    if ref.year:
        score += 0.20
    if ref.title:
        score += 0.25
    if ref.journal:
        score += 0.15
    if ref.doi or ref.pages:
        score += 0.15

    return score


def get_completeness_report(references: list[Citation]) -> dict:
    """
    Generate a completeness report for all references.

    Returns:
        Dict with statistics and per-reference scores
    """
    scores = []
    incomplete_count = 0
    missing_fields_count = {
        "authors": 0,
        "year": 0,
        "title": 0,
        "journal": 0,
        "identifier": 0,
    }

    for ref in references:
        score = get_completeness_score(ref)
        scores.append({"id": ref.id, "score": score})

        if score < 1.0:
            incomplete_count += 1
            if not ref.authors:
                missing_fields_count["authors"] += 1
            if not ref.year:
                missing_fields_count["year"] += 1
            if not ref.title:
                missing_fields_count["title"] += 1
            if not ref.journal:
                missing_fields_count["journal"] += 1
            if not ref.doi and not ref.pages:
                missing_fields_count["identifier"] += 1

    avg_score = sum(s["score"] for s in scores) / len(scores) if scores else 0.0

    return {
        "total_references": len(references),
        "incomplete_count": incomplete_count,
        "average_score": round(avg_score, 2),
        "missing_fields_count": missing_fields_count,
        "per_reference_scores": scores,
    }


def _truncate(text: str, max_length: int) -> str:
    """Truncate text to max_length, adding ellipsis if needed."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."
