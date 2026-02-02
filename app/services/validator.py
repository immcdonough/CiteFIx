"""Citation validation service for checking citation coverage."""

from collections import Counter
from dataclasses import dataclass
from typing import Optional

from app.models.schemas import (
    Citation,
    CitationType,
    InTextCitation,
    IssueSeverity,
    ValidationIssue,
    ValidationReport,
)
from app.services.citation_detector import match_citations_to_references
from app.services.completeness_checker import check_reference_completeness
from app.services.duplicate_detector import detect_duplicates
from app.services.journal_normalizer import check_journal_consistency


@dataclass
class ValidationContext:
    """Context for validation operations."""
    in_text_citations: list[InTextCitation]
    references: list[Citation]
    citation_type: CitationType


@dataclass
class QuickCheckResult:
    """Result of quick validation check (no web search)."""
    total_citations: int
    total_references: int
    matched_count: int
    unmatched_count: int
    estimated_time_seconds: int  # Estimated time for full validation with web search

    @property
    def needs_web_search(self) -> bool:
        return self.unmatched_count > 0

    @property
    def time_estimate_str(self) -> str:
        if self.estimated_time_seconds < 60:
            return f"~{self.estimated_time_seconds} seconds"
        minutes = self.estimated_time_seconds // 60
        return f"~{minutes}-{minutes + 1} minutes"


def quick_check_citations(
    in_text_citations: list[InTextCitation],
    references: list[Citation],
) -> QuickCheckResult:
    """
    Quick check to count matched/unmatched citations without web search.
    Use this to estimate processing time before full validation.
    """
    from app.services.citation_detector import match_citations_to_references

    match_result = match_citations_to_references(in_text_citations, references)

    matched_count = len([c for c in in_text_citations if match_result.matches.get(c.text)])
    unmatched_count = len(in_text_citations) - matched_count

    # Estimate ~8 seconds per unmatched citation for web search
    estimated_time = unmatched_count * 8

    return QuickCheckResult(
        total_citations=len(in_text_citations),
        total_references=len(references),
        matched_count=matched_count,
        unmatched_count=unmatched_count,
        estimated_time_seconds=estimated_time,
    )


def validate_citations(
    in_text_citations: list[InTextCitation],
    references: list[Citation],
    citation_type: CitationType = CitationType.AUTHOR_YEAR,
    enable_web_search: bool = True,
    progress_callback: Optional[callable] = None,
    check_completeness: bool = True,
    detect_duplicates_advanced: bool = True,
    check_retractions: bool = False,
    check_journal_names: bool = True,
    retraction_checker_email: Optional[str] = None,
) -> ValidationReport:
    """
    Validate that all citations match references and vice versa.

    Args:
        in_text_citations: List of in-text citations found
        references: List of reference entries
        citation_type: Type of citation system used
        enable_web_search: Whether to search CrossRef for unmatched citations
        progress_callback: Optional callback for progress updates
        check_completeness: Whether to check for incomplete references
        detect_duplicates_advanced: Whether to use advanced duplicate detection
        check_retractions: Whether to check for retracted papers (requires internet)
        check_journal_names: Whether to check for inconsistent journal naming
        retraction_checker_email: Email for CrossRef polite pool (faster rate limits)

    Returns:
        ValidationReport with findings
    """
    issues: list[ValidationIssue] = []

    # Match citations to references (two-pass: exact first, then fuzzy)
    match_result = match_citations_to_references(in_text_citations, references)

    # Track which references are cited
    cited_ref_ids: set[str] = set()
    for ref_ids in match_result.matches.values():
        cited_ref_ids.update(ref_ids)

    # Check for unmatched in-text citations (missing references)
    unmatched_citations = _find_unmatched_citations(in_text_citations, match_result.matches)

    # Process unmatched citations with optional progress reporting
    for i, citation in enumerate(unmatched_citations):
        if progress_callback:
            progress_callback(i + 1, len(unmatched_citations))

        suggestion = _suggest_reference_fix(
            citation, references, search_web=enable_web_search
        )
        issues.append(ValidationIssue(
            issue_type="missing_reference",
            description=f"In-text citation has no matching reference",
            citation_text=citation.text,
            suggestion=suggestion,
        ))

    # Generate warnings for fuzzy matches (spelling/year mismatches)
    for citation_text, fuzzy_refs in match_result.fuzzy_matches.items():
        for fuzzy_info in fuzzy_refs:
            # Only generate spelling warning if author name was fuzzy (not just year)
            if fuzzy_info.author_is_fuzzy:
                issues.append(ValidationIssue(
                    issue_type="spelling_mismatch",
                    description="Possible author name spelling mismatch",
                    citation_text=citation_text,
                    suggestion=f"Citation uses '{fuzzy_info.citation_author.title()}' but reference has "
                               f"'{fuzzy_info.ref_author.title()}'. Verify correct spelling.",
                ))
            # Generate year warning if year was fuzzy (but author was exact)
            elif fuzzy_info.year_is_fuzzy and fuzzy_info.citation_year and fuzzy_info.ref_year:
                issues.append(ValidationIssue(
                    issue_type="year_mismatch",
                    description="Year differs between citation and reference",
                    citation_text=citation_text,
                    suggestion=f"Citation says {fuzzy_info.citation_year} but reference has {fuzzy_info.ref_year}. "
                               f"Verify correct year.",
                ))

    # Check for uncited references
    uncited_refs = _find_uncited_references(references, cited_ref_ids)
    for ref in uncited_refs:
        # Check if there's a near-match in unmatched citations (possible typo)
        suggestion = _suggest_citation_for_uncited_ref(ref, unmatched_citations)
        issues.append(ValidationIssue(
            issue_type="uncited_reference",
            description=f"Reference is not cited in the text",
            citation_text=ref.raw_text[:100] + "..." if len(ref.raw_text) > 100 else ref.raw_text,
            suggestion=suggestion,
        ))

    # Check for duplicate references (use advanced detection if enabled)
    if detect_duplicates_advanced:
        # Advanced duplicate detection with fuzzy matching
        duplicate_issues = detect_duplicates(references)
        issues.extend(duplicate_issues)
    else:
        # Simple duplicate detection (legacy)
        duplicates = _find_duplicate_references(references)
        for dup_group in duplicates:
            issues.append(ValidationIssue(
                issue_type="duplicate_reference",
                description=f"Possible duplicate references found",
                citation_text="; ".join(r.id for r in dup_group),
                suggestion="Review and merge these references if they are duplicates",
            ))

    # Check for citation format consistency
    format_issues = _check_format_consistency(in_text_citations)
    issues.extend(format_issues)

    # Check for "and" instead of "&" in parenthetical citations
    ampersand_issues = _check_ampersand_usage(in_text_citations)
    issues.extend(ampersand_issues)

    # Check for incomplete references (missing required fields)
    if check_completeness:
        completeness_issues = check_reference_completeness(references)
        issues.extend(completeness_issues)

    # Check for inconsistent journal naming
    if check_journal_names:
        journal_issues = check_journal_consistency(references)
        issues.extend(journal_issues)

    # Check for retracted papers (requires internet access)
    if check_retractions:
        from app.services.retraction_checker import RetractionChecker
        retraction_checker = RetractionChecker(email=retraction_checker_email)
        retraction_issues = retraction_checker.check_references(references)
        issues.extend(retraction_issues)

    # Calculate matched count (includes both exact and fuzzy matches)
    matched_count = len([c for c in in_text_citations if match_result.matches.get(c.text)])

    return ValidationReport(
        total_in_text_citations=len(in_text_citations),
        total_references=len(references),
        matched_citations=matched_count,
        issues=issues,
        is_valid=len(issues) == 0,
    )


def _find_unmatched_citations(
    citations: list[InTextCitation],
    matches: dict[str, list[str]],
) -> list[InTextCitation]:
    """Find unique citations that don't match any reference."""
    unmatched: list[InTextCitation] = []
    seen_texts: set[str] = set()

    for citation in citations:
        # Skip if we've already seen this citation text
        if citation.text in seen_texts:
            continue

        matched_refs = matches.get(citation.text, [])
        if not matched_refs:
            unmatched.append(citation)
            seen_texts.add(citation.text)

    return unmatched


def _find_uncited_references(
    references: list[Citation],
    cited_ids: set[str],
) -> list[Citation]:
    """Find references that are not cited in the text."""
    uncited: list[Citation] = []

    for ref in references:
        if ref.id not in cited_ids:
            uncited.append(ref)

    return uncited


def _find_duplicate_references(references: list[Citation]) -> list[list[Citation]]:
    """Find potential duplicate references."""
    duplicates: list[list[Citation]] = []
    seen: dict[str, list[Citation]] = {}

    for ref in references:
        # Create a normalized key for comparison
        key = _normalize_reference_key(ref)
        if key in seen:
            seen[key].append(ref)
        else:
            seen[key] = [ref]

    # Return groups with more than one reference
    for key, refs in seen.items():
        if len(refs) > 1:
            duplicates.append(refs)

    return duplicates


def _normalize_reference_key(ref: Citation) -> str:
    """Create normalized key for duplicate detection."""
    parts: list[str] = []

    # Use first author's last name
    if ref.authors:
        author = ref.authors[0].lower()
        if "," in author:
            author = author.split(",")[0]
        else:
            author = author.split()[-1] if author.split() else author
        parts.append(author[:10])  # First 10 chars of last name

    # Use year
    if ref.year:
        parts.append(str(ref.year))

    # Use first few words of title
    if ref.title:
        title_words = ref.title.lower().split()[:3]
        parts.append("_".join(title_words))

    return "|".join(parts)


def _check_format_consistency(citations: list[InTextCitation]) -> list[ValidationIssue]:
    """Check for inconsistent citation formats."""
    issues: list[ValidationIssue] = []

    if not citations:
        return issues

    # Count citation types
    type_counts = Counter(c.citation_type for c in citations)

    # If mixed types, report inconsistency
    if len(type_counts) > 1:
        dominant_type = type_counts.most_common(1)[0][0]
        minority_types = [t for t in type_counts if t != dominant_type]

        for minority in minority_types:
            minority_citations = [c for c in citations if c.citation_type == minority]
            for citation in minority_citations[:3]:  # Report up to 3 examples
                issues.append(ValidationIssue(
                    issue_type="inconsistent_format",
                    description=f"Citation format ({minority.value}) differs from dominant format ({dominant_type.value})",
                    citation_text=citation.text,
                    suggestion=f"Consider reformatting to match {dominant_type.value} style",
                ))

    return issues


def _check_ampersand_usage(citations: list[InTextCitation]) -> list[ValidationIssue]:
    """Check for 'and' used instead of '&' inside parenthetical citations."""
    import re
    issues: list[ValidationIssue] = []

    for citation in citations:
        # Only check parenthetical citations (not inline narrative style)
        if citation.citation_type != CitationType.AUTHOR_YEAR:
            continue

        # Check if citation text contains "and" between authors inside parentheses
        # Pattern: (Author and Author, Year) - "and" should be "&"
        if re.search(r'\([^)]*\s+and\s+[^)]*\d{4}', citation.text, re.IGNORECASE):
            issues.append(ValidationIssue(
                issue_type="style_warning",
                description="Use '&' instead of 'and' inside parenthetical citations",
                citation_text=citation.text,
                suggestion=citation.text.replace(' and ', ' & ').replace(' And ', ' & '),
            ))

    return issues


def _suggest_reference_fix(
    citation: InTextCitation,
    references: list[Citation],
    search_web: bool = True,
) -> Optional[str]:
    """Suggest a fix for an unmatched citation."""
    import re

    # Extract author names and year from citation
    citation_text = citation.text
    citation_authors = _extract_citation_author_names(citation_text)
    citation_year = None
    year_match = re.search(r'\b(19|20)\d{2}\b', citation_text)
    if year_match:
        citation_year = int(year_match.group(0))

    # Get context for keyword matching
    context = citation.context if hasattr(citation, 'context') else ""

    # Score all references and find best matches
    scored_refs: list[tuple[float, Citation, str]] = []

    for ref in references:
        score, reason = _calculate_similarity_detailed(
            citation_authors, citation_year, ref, context
        )
        if score > 0:
            scored_refs.append((score, ref, reason))

    # Sort by score descending
    scored_refs.sort(key=lambda x: x[0], reverse=True)

    # Check if we have a good local match
    # A good match should have: author as FIRST author + reasonable year
    best_local = None
    if scored_refs:
        best_score, best_ref, reason = scored_refs[0]

        # Check if the first author matches (not just any co-author)
        first_author_match = False
        if best_ref.authors and citation_authors:
            first_ref_author = _get_ref_last_name(best_ref.authors[0]).lower()
            first_citation_author = citation_authors[0].lower()
            first_author_match = (
                first_citation_author == first_ref_author or
                first_citation_author in first_ref_author or
                first_ref_author in first_citation_author
            )

        # Good match: first author matches AND score is decent
        if first_author_match and best_score >= 0.4:
            ref_preview = best_ref.raw_text[:80]
            if len(best_ref.raw_text) > 80:
                ref_preview += "..."

            if reason:
                return f"Did you mean: {ref_preview} ({reason})"
            return f"Did you mean: {ref_preview}"

        # Save for potential weak match fallback
        best_local = (best_score, best_ref, reason)

    # No good local match - try web search if enabled
    if search_web and citation_authors and citation_year:
        web_result = _search_crossref_for_citation(
            citation_authors, citation_year, context
        )
        if web_result:
            # Also show weak local match if exists
            if best_local and best_local[0] > 0.2:
                _, local_ref, local_reason = best_local
                local_preview = local_ref.raw_text[:60] + "..."
                return f"{web_result}\n    Or in your refs: {local_preview}"
            return web_result

    # Fall back to best local match if any, or generic message
    if best_local:
        best_score, best_ref, reason = best_local
        ref_preview = best_ref.raw_text[:80]
        if len(best_ref.raw_text) > 80:
            ref_preview += "..."
        return f"Weak match (co-author?): {ref_preview}"

    return "Add a corresponding reference to the bibliography"


def _suggest_citation_for_uncited_ref(
    ref: Citation,
    unmatched_citations: list[InTextCitation],
) -> str:
    """
    Suggest a possible citation match for an uncited reference.
    Checks for typos/near-matches in unmatched citations.
    """
    import re

    if not ref.authors:
        return "Consider removing this reference or adding a citation"

    ref_first_author = _get_ref_last_name(ref.authors[0])
    ref_year = ref.year

    best_match = None
    best_reason = ""

    for citation in unmatched_citations:
        # Extract author and year from citation
        citation_authors = _extract_citation_author_names(citation.text)
        year_match = re.search(r'\b(19|20)\d{2}\b', citation.text)
        citation_year = int(year_match.group(0)) if year_match else None

        if not citation_authors:
            continue

        first_cit_author = citation_authors[0]

        # Check for fuzzy match
        is_match, reason = _fuzzy_author_match(first_cit_author, ref_first_author)

        if is_match and reason:  # Only if it's a typo match, not exact
            # Check year compatibility
            year_ok = True
            year_note = ""
            if citation_year and ref_year:
                year_diff = abs(citation_year - ref_year)
                if year_diff > 2:
                    year_ok = False
                elif year_diff > 0:
                    year_note = f"; year differs: {ref_year} vs {citation_year}"

            if year_ok:
                best_match = citation.text
                best_reason = reason + year_note
                break

    if best_match:
        return f"Possible typo match: {best_match} ({best_reason})"

    return "Consider removing this reference or adding a citation"


def _search_crossref_for_citation(
    authors: list[str],
    year: int,
    context: str,
    max_results: int = 3,
) -> Optional[str]:
    """
    Search CrossRef for a citation not found in references.

    Args:
        authors: Author last names from citation
        year: Year from citation
        context: Surrounding text for keyword extraction
        max_results: Maximum number of results to return

    Returns:
        Suggestion string with up to max_results matches, or None
    """
    try:
        from habanero import Crossref
        cr = Crossref()

        first_author = authors[0] if authors else ""
        if not first_author:
            return None

        # Extract meaningful keywords from context
        context_keywords = _extract_keywords(context)
        specific_keywords = [k for k in context_keywords if len(k) >= 4]
        sorted_keywords = sorted(specific_keywords, key=len, reverse=True)[:4]

        # Neuroscience/medical terms for relevance filtering
        neuro_terms = {
            'sleep', 'insomnia', 'brain', 'neural', 'cortex', 'fmri', 'mri',
            'neuroimaging', 'hippocampus', 'amygdala', 'prefrontal', 'cerebral',
            'resting-state', 'resting state', 'gray matter', 'white matter',
            'eeg', 'cogniti', 'memory', 'attention', 'anxiety', 'depression',
            'functional connectivity', 'rsfc', 'bold', 'magnetic resonance',
            'emotion', 'network', 'disorder',
        }

        context_lower = context.lower()
        context_is_neuro = any(t in context_lower for t in neuro_terms)

        # Try multiple search strategies with different keyword combinations
        search_queries = [
            f"{first_author} {' '.join(sorted_keywords[:3])}",  # Author + top 3 keywords
            f"{first_author} {' '.join(sorted_keywords[:2])}",  # Author + top 2 keywords
            f"{first_author} brain",  # Author + brain (common in neuro papers)
            first_author,  # Just author name
        ]

        found_matches: list[dict] = []
        seen_dois: set[str] = set()

        for query in search_queries:
            if len(found_matches) >= max_results:
                break

            results = cr.works(
                query=query,
                filter={"from-pub-date": str(year - 1), "until-pub-date": str(year + 1)},
                limit=15,
                select="DOI,title,author,published-print,published-online",
            )

            if not results or "message" not in results:
                continue

            items = results["message"].get("items", [])

            for item in items:
                if len(found_matches) >= max_results:
                    break

                doi = item.get("DOI", "")
                if doi in seen_dois:
                    continue

                item_authors = item.get("author", [])
                if not item_authors:
                    continue

                # Check if FIRST author matches
                first_item_author = item_authors[0].get("family", "").lower()
                if not (first_author.lower() in first_item_author or
                        first_item_author in first_author.lower()):
                    continue

                # Check year is close
                item_year = _extract_crossref_year(item)
                if item_year and abs(item_year - year) > 2:
                    continue

                # Check topic relevance
                title = item.get("title", ["Unknown"])[0] if item.get("title") else "Unknown"
                title_lower = title.lower()

                if context_is_neuro:
                    title_is_neuro = any(t in title_lower for t in neuro_terms)
                    if not title_is_neuro:
                        continue

                # Good match found!
                seen_dois.add(doi)
                found_matches.append({
                    "authors": item_authors,
                    "year": item_year,
                    "title": title,
                    "doi": doi,
                })

        if not found_matches:
            return None

        # Format results
        lines = ["[WEB SEARCH] Possible matches:"]
        for i, match in enumerate(found_matches, 1):
            author_str = _format_crossref_authors(match["authors"][:3])
            if len(match["authors"]) > 3:
                author_str += " et al."

            title = match["title"][:60]
            if len(match["title"]) > 60:
                title += "..."

            year_note = ""
            if match["year"] and match["year"] != year:
                year_note = f" [year: {match['year']}]"

            doi_link = f" https://doi.org/{match['doi']}" if match["doi"] else ""

            lines.append(f"  {i}. {author_str} ({match['year']}). {title}{year_note}{doi_link}")

        return "\n".join(lines)

    except Exception as e:
        # Don't fail validation if web search fails
        return None


def _extract_crossref_year(item: dict) -> Optional[int]:
    """Extract year from CrossRef item."""
    for field in ["published-print", "published-online", "issued"]:
        if field in item and "date-parts" in item[field]:
            parts = item[field]["date-parts"]
            if parts and parts[0] and len(parts[0]) > 0:
                return parts[0][0]
    return None


def _format_crossref_authors(authors: list[dict]) -> str:
    """Format CrossRef author list."""
    names = []
    for author in authors:
        given = author.get("given", "")
        family = author.get("family", "")
        if family:
            if given:
                # Get initials
                initials = "".join(w[0] for w in given.split() if w)
                names.append(f"{family} {initials}")
            else:
                names.append(family)
    return ", ".join(names)


def _normalize_dashes(text: str) -> str:
    """Normalize all dash/hyphen variants to standard hyphen-minus for comparison."""
    # Replace en dash, em dash, figure dash, hyphen, non-breaking hyphen with standard hyphen
    dash_chars = '\u2010\u2011\u2012\u2013\u2014'
    for dash in dash_chars:
        text = text.replace(dash, '-')
    return text


def _extract_citation_author_names(citation_text: str) -> list[str]:
    """Extract author last names from in-text citation."""
    import re

    # Remove parentheses, year, "et al.", and "and colleagues"
    text = re.sub(r'[()]', '', citation_text)
    text = re.sub(r',?\s*\d{4}[a-z]?', '', text)
    text = re.sub(r'\s+et\s+al\.?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+and\s+colleagues', '', text, flags=re.IGNORECASE)
    text = text.strip()

    # Split on & or "and" (but not "and colleagues" which was already removed)
    if ' & ' in text:
        authors = text.split(' & ')
    elif ' and ' in text.lower():
        authors = re.split(r'\s+and\s+', text, flags=re.IGNORECASE)
    else:
        authors = [text]

    # Return lowercased and dash-normalized for consistent comparison
    return [_normalize_dashes(a.strip().lower()) for a in authors if a.strip()]


def _get_ref_last_name(author: str) -> str:
    """Extract last name from reference author."""
    import re
    author = author.strip()

    # Format: "Smith, John" or "Smith, J."
    if "," in author:
        return _normalize_dashes(author.split(",")[0].strip().lower())

    # Format: "Smith J" or "Smith JA" (Vancouver - LastName followed by initials)
    # Also handle hyphenated names like "Fernandez-Mendoza J"
    match = re.match(r'^([A-Za-z][a-zA-Z\-\u2010\u2011\u2012\u2013\u2014]+(?:\s+[A-Za-z][a-zA-Z\-\u2010\u2011\u2012\u2013\u2014]+)*)\s+[A-Z]+', author)
    if match:
        return _normalize_dashes(match.group(1).lower())

    # Format: "John Smith" - assume last word is last name
    parts = author.split()
    if parts:
        # Check if last part looks like initials
        if len(parts) > 1 and re.match(r'^[A-Z]+\.?$', parts[-1]):
            return _normalize_dashes(parts[0].lower())
        return _normalize_dashes(parts[-1].lower())

    return _normalize_dashes(author.lower())


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def _fuzzy_author_match(citation_author: str, ref_name: str) -> tuple[bool, str]:
    """
    Check if author names match with fuzzy matching for typos.

    Returns:
        Tuple of (is_match, reason_string)
    """
    # Normalize dashes for comparison (Word often uses en dash instead of hyphen)
    citation_author = _normalize_dashes(citation_author)
    ref_name = _normalize_dashes(ref_name)

    # Exact match
    if citation_author == ref_name:
        return True, ""

    # Substring match - but flag as potential typo if length difference is small
    if citation_author in ref_name or ref_name in citation_author:
        len_diff = abs(len(citation_author) - len(ref_name))
        if len_diff <= 2:
            # Small length difference suggests typo (e.g., "Ficek-Tani" vs "Ficek-Tania")
            return True, f"possible typo: '{ref_name}' not '{citation_author}'"
        # Large length difference is likely legitimate (e.g., compound names)
        return True, ""

    # Fuzzy match for typos (allow 1-2 character differences for longer names)
    distance = _levenshtein_distance(citation_author, ref_name)
    max_distance = 1 if len(citation_author) <= 6 else 2

    if distance <= max_distance:
        return True, f"possible typo: '{ref_name}' not '{citation_author}'"

    return False, ""


def _calculate_similarity_detailed(
    citation_authors: list[str],
    citation_year: Optional[int],
    ref: Citation,
    context: str = "",
) -> tuple[float, str]:
    """
    Calculate similarity between citation and reference.

    Args:
        citation_authors: Author names extracted from citation
        citation_year: Year from citation
        ref: Reference to compare against
        context: Surrounding text context for keyword matching

    Returns:
        Tuple of (score, reason_string)
    """
    score = 0.0
    reasons: list[str] = []

    # Get reference author last names
    ref_last_names = [_get_ref_last_name(a) for a in ref.authors]

    # Check author match with fuzzy matching (most important - 0.5 weight)
    author_matched = False
    for citation_author in citation_authors:
        for ref_name in ref_last_names:
            is_match, match_reason = _fuzzy_author_match(citation_author, ref_name)
            if is_match:
                author_matched = True
                score += 0.5
                if match_reason:
                    reasons.append(match_reason)
                break
        if author_matched:
            break

    # Check year match or near-match (0.3 weight)
    if citation_year and ref.year:
        year_diff = abs(citation_year - ref.year)
        if year_diff == 0:
            score += 0.3
        elif year_diff == 1:
            score += 0.25
            reasons.append(f"year is {ref.year}, not {citation_year}")
        elif year_diff == 2:
            score += 0.2
            reasons.append(f"year is {ref.year}, not {citation_year}")
        elif year_diff <= 5:
            score += 0.1
            reasons.append(f"year is {ref.year}, not {citation_year}")

    # Check context keyword match against reference title (0.2 weight)
    if context and ref.title:
        keyword_score = _calculate_keyword_overlap(context, ref.title)
        score += keyword_score * 0.2
        if keyword_score > 0.3 and not author_matched:
            # If good keyword match but no author match, still consider it
            # This helps when citation has typo in author name
            reasons.append("title keywords match context")

    # If no author match and low keyword score, not a good suggestion
    if not author_matched and score < 0.15:
        return 0.0, ""

    reason_str = "; ".join(reasons) if reasons else ""
    return score, reason_str


# Common English stopwords to ignore in keyword matching
STOPWORDS = {
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of',
    'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been', 'be', 'have',
    'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may',
    'might', 'must', 'shall', 'can', 'need', 'dare', 'ought', 'used', 'it', 'its',
    'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'we', 'they', 'what',
    'which', 'who', 'whom', 'when', 'where', 'why', 'how', 'all', 'each', 'every',
    'both', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not',
    'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just', 'also', 'now',
    'into', 'over', 'after', 'before', 'between', 'under', 'again', 'further',
    'then', 'once', 'here', 'there', 'about', 'above', 'below', 'during', 'through',
}


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text, excluding stopwords."""
    import re

    # Lowercase and extract words
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())

    # Filter out stopwords and very short words
    keywords = {w for w in words if w not in STOPWORDS and len(w) >= 3}

    return keywords


def _calculate_keyword_overlap(context: str, title: str) -> float:
    """
    Calculate keyword overlap between context and reference title.

    Returns:
        Score from 0.0 to 1.0 based on keyword overlap
    """
    context_keywords = _extract_keywords(context)
    title_keywords = _extract_keywords(title)

    if not context_keywords or not title_keywords:
        return 0.0

    # Find overlapping keywords
    overlap = context_keywords & title_keywords

    if not overlap:
        return 0.0

    # Score based on what fraction of title keywords appear in context
    # This rewards matching important title words
    title_coverage = len(overlap) / len(title_keywords)

    # Also consider absolute number of matches (more matches = more confident)
    match_bonus = min(len(overlap) / 3, 1.0)  # Cap at 3+ matches

    return (title_coverage + match_bonus) / 2


def _calculate_similarity(citation: InTextCitation, ref: Citation) -> float:
    """Calculate similarity between citation and reference (simple version)."""
    import re

    citation_authors = _extract_citation_author_names(citation.text)
    citation_year = None
    year_match = re.search(r'\b(19|20)\d{2}\b', citation.text)
    if year_match:
        citation_year = int(year_match.group(0))

    context = citation.context if hasattr(citation, 'context') else ""
    score, _ = _calculate_similarity_detailed(citation_authors, citation_year, ref, context)
    return score


def generate_validation_summary(report: ValidationReport) -> str:
    """Generate a human-readable validation summary."""
    lines: list[str] = []

    lines.append("=" * 50)
    lines.append("CITATION VALIDATION REPORT")
    lines.append("=" * 50)
    lines.append("")

    # Statistics
    lines.append(f"Total in-text citations: {report.total_in_text_citations}")
    lines.append(f"Total references: {report.total_references}")
    lines.append(f"Matched citations: {report.matched_citations}")
    lines.append("")

    if report.is_valid:
        lines.append("Status: VALID - All citations match references")
    else:
        lines.append(f"Status: ISSUES FOUND - {len(report.issues)} issue(s)")
        lines.append("")

        # Group issues by type
        issues_by_type: dict[str, list[ValidationIssue]] = {}
        for issue in report.issues:
            if issue.issue_type not in issues_by_type:
                issues_by_type[issue.issue_type] = []
            issues_by_type[issue.issue_type].append(issue)

        for issue_type, issues in issues_by_type.items():
            lines.append(f"\n{issue_type.upper().replace('_', ' ')} ({len(issues)}):")
            lines.append("-" * 40)
            for issue in issues:
                lines.append(f"  - {issue.description}")
                if issue.citation_text:
                    lines.append(f"    Citation: {issue.citation_text}")
                if issue.suggestion:
                    lines.append(f"    Suggestion: {issue.suggestion}")

    lines.append("")
    lines.append("=" * 50)

    return "\n".join(lines)
