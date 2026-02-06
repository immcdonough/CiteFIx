"""Citation detection service for finding in-text citations and parsing references."""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.models.schemas import Citation, CitationType, InTextCitation


class MatchType(Enum):
    """Type of match between citation and reference."""
    NONE = "none"           # No match
    EXACT = "exact"         # Exact author name match
    FUZZY = "fuzzy"         # Fuzzy match (possible spelling issue)


@dataclass
class CitationMatchDetail:
    """Detailed result of matching a citation to a reference."""
    match_type: MatchType
    author_is_fuzzy: bool = False  # True if author name required fuzzy matching
    year_is_fuzzy: bool = False    # True if year required tolerance
    citation_author: str = ""
    ref_author: str = ""
    citation_year: Optional[int] = None
    ref_year: Optional[int] = None


@dataclass
class DetectionResult:
    """Result of citation detection."""
    in_text_citations: list[InTextCitation]
    references: list[Citation]
    detected_type: CitationType


# Patterns for different citation styles

# Common dash/hyphen characters that may appear in names (Word often converts - to en dash)
# Includes: hyphen-minus (-), en dash (–), em dash (—), hyphen (‐), non-breaking hyphen (‑)
DASH_CHARS = r"\-\u2010\u2011\u2012\u2013\u2014"

# Apostrophe characters that may appear in names (Word often converts ' to curly apostrophe)
# Includes: apostrophe ('), right single quotation mark ('), modifier letter apostrophe (ʼ)
APOS_CHARS = r"'\u2019\u02BC"

# Author name pattern: handles hyphenated (Ancoli-Israel, Fernandez-Mendoza), apostrophes (O'Connor)
# Supports various Unicode dash and apostrophe characters that Word may insert
AUTHOR_NAME = r"[A-Z][a-zA-Z" + APOS_CHARS + DASH_CHARS + r"]+"

# Single author-year: (Smith, 2020), (Smith & Jones, 2020), (Smith et al., 2020)
SINGLE_AUTHOR_YEAR = AUTHOR_NAME + r'(?:\s+(?:&|and)\s+' + AUTHOR_NAME + r')?(?:\s+et\s+al\.?)?,?\s*\d{4}[a-z]?'

# Author-year pattern: matches single or multiple semicolon-separated citations
# e.g., (Smith, 2020) or (Smith, 2020; Jones & Brown, 2021)
AUTHOR_YEAR_PATTERN = re.compile(
    r'\((' + SINGLE_AUTHOR_YEAR + r'(?:\s*;\s*' + SINGLE_AUTHOR_YEAR + r')*)\)',
    re.UNICODE
)

# Pattern to find all parenthetical expressions for secondary scanning
# Used to find citations mixed with abbreviations like (MoCA; Nasreddine et al., 2005)
PARENTHETICAL_PATTERN = re.compile(r'\(([^()]+)\)', re.UNICODE)

# Pattern to extract individual citations from multi-citation string
INDIVIDUAL_CITATION_PATTERN = re.compile(
    r'(' + AUTHOR_NAME + r'(?:\s+(?:&|and)\s+' + AUTHOR_NAME + r')?(?:\s+et\s+al\.?)?),?\s*(\d{4}[a-z]?)',
    re.UNICODE
)

# Author year inline: Smith (2020), Smith and Jones (2020), Smith et al., (2020)
# Handles optional comma after "et al." which is common in narrative citations
# Also handles "and colleagues" as alternative to "et al."
AUTHOR_INLINE_PATTERN = re.compile(
    r'(' + AUTHOR_NAME + r'(?:\s+(?:&|and)\s+' + AUTHOR_NAME + r')?(?:\s+et\s+al\.?,?|\s+and\s+colleagues)?)\s*\((\d{4}[a-z]?)\)',
    re.UNICODE
)

# Numeric bracketed: [1], [1, 2], [1-3]
NUMERIC_BRACKET_PATTERN = re.compile(
    r'\[(\d+(?:\s*[-,]\s*\d+)*)\]'
)

# Numeric superscript: represented as ^1, ^1,2, ^1-3 in plain text
NUMERIC_SUPER_PATTERN = re.compile(
    r'\^(\d+(?:\s*[-,]\s*\d+)*)'
)

# Reference parsing patterns
# Standard author-year reference: Smith, J. (2020). Title. Journal, 1(2), 3-4.
AUTHOR_YEAR_REF_PATTERN = re.compile(
    r'^(?P<authors>[^(]+)\((?P<year>\d{4}[a-z]?)\)\.\s*(?P<title>[^.]+)\.'
)

# Harvard style reference (year without parentheses): Smith, J., 2020. Title. Journal.
# Format: Authors, Year. Title. Journal, Volume(Issue), Pages.
# Capture everything after year to parse title/journal/volume separately
HARVARD_REF_PATTERN = re.compile(
    r'^(?P<authors>.+?),\s*(?P<year>(?:19|20)\d{2}[a-z]?)\.\s*(?P<remainder>.+)$'
)

# Numbered reference: 1. Smith J. Title. Journal. 2020;1(2):3-4.
NUMBERED_REF_PATTERN = re.compile(
    r'^(?:\[?\d+\]?\.?\s*)(?P<authors>[^.]+)\.\s*(?P<title>[^.]+)\.'
)

# Vancouver/medical style: Smith J, Jones B. Title. Journal 2020;1(2):3-4.
# Authors are "LastName Initials" separated by commas, ends with period before title
# Pattern: Match text before first ". " that ends with capital letter(s) (initials)
# This handles hyphenated names, apostrophes, multi-part names like "Van der Berg"
# Title can end with . ? or ! (for questions like "Do sleep complaints contribute...?")
VANCOUVER_REF_PATTERN = re.compile(
    r"^(?P<authors>.+?[A-Z]{1,4})\.\s+(?P<title>[A-Z][^.?!]+[.?!])"
)


def detect_citations(text: str, context_chars: int = 150) -> DetectionResult:
    """
    Detect all in-text citations in the given text.

    Args:
        text: The document text to search
        context_chars: Number of characters to capture before/after citation for context

    Returns:
        DetectionResult with found citations and detected type
    """
    citations: list[InTextCitation] = []
    detected_type = CitationType.AUTHOR_YEAR

    # Try author-year first (most common in academic writing)
    author_year_matches = list(AUTHOR_YEAR_PATTERN.finditer(text))
    author_inline_matches = list(AUTHOR_INLINE_PATTERN.finditer(text))

    # Try numeric patterns
    numeric_matches = list(NUMERIC_BRACKET_PATTERN.finditer(text))

    # Determine dominant citation type
    author_count = len(author_year_matches) + len(author_inline_matches)
    numeric_count = len(numeric_matches)

    if numeric_count > author_count:
        detected_type = CitationType.NUMERIC
        # Process numeric citations
        for match in numeric_matches:
            context = _extract_context(text, match.start(), match.end(), context_chars)
            citation = InTextCitation(
                text=match.group(0),
                start_pos=match.start(),
                end_pos=match.end(),
                citation_type=CitationType.NUMERIC,
                reference_ids=_parse_numeric_refs(match.group(1)),
                context=context,
            )
            citations.append(citation)
    else:
        # Process author-year citations (may contain multiple semicolon-separated citations)
        for match in author_year_matches:
            context = _extract_context(text, match.start(), match.end(), context_chars)
            full_text = match.group(0)  # e.g., "(Ashburner, 2007; Ashburner & Friston, 2005)"
            inner_text = match.group(1)  # e.g., "Ashburner, 2007; Ashburner & Friston, 2005"

            # Split into individual citations and create separate InTextCitation for each
            individual_matches = list(INDIVIDUAL_CITATION_PATTERN.finditer(inner_text))
            for ind_match in individual_matches:
                author = ind_match.group(1)
                year = ind_match.group(2)
                # Create citation text in standard format
                cit_text = f"({author}, {year})"
                citation = InTextCitation(
                    text=cit_text,
                    start_pos=match.start(),
                    end_pos=match.end(),
                    citation_type=CitationType.AUTHOR_YEAR,
                    reference_ids=[_make_ref_id(author, year)],
                    context=context,
                )
                citations.append(citation)

        # Scan all parenthetical expressions for citations mixed with other text
        # This handles cases like (MoCA; Nasreddine et al., 2005), (see Smith, 2020)
        for paren_match in PARENTHETICAL_PATTERN.finditer(text):
            # Check if this parenthetical was already fully captured by AUTHOR_YEAR_PATTERN
            already_captured = any(
                m.start() == paren_match.start() and m.end() == paren_match.end()
                for m in author_year_matches
            )
            if already_captured:
                continue

            paren_content = paren_match.group(1)
            # Look for author-year citations within this parenthetical
            individual_matches = list(INDIVIDUAL_CITATION_PATTERN.finditer(paren_content))

            for ind_match in individual_matches:
                author = ind_match.group(1)
                year = ind_match.group(2)
                cit_text = f"({author}, {year})"

                # Check if this specific citation was already found
                already_found = any(
                    c.text == cit_text and
                    paren_match.start() <= c.start_pos <= paren_match.end()
                    for c in citations
                )
                if already_found:
                    continue

                context = _extract_context(text, paren_match.start(), paren_match.end(), context_chars)
                citation = InTextCitation(
                    text=cit_text,
                    start_pos=paren_match.start(),
                    end_pos=paren_match.end(),
                    citation_type=CitationType.AUTHOR_YEAR,
                    reference_ids=[_make_ref_id(author, year)],
                    context=context,
                )
                citations.append(citation)

        for match in author_inline_matches:
            # Check if this overlaps with a parenthetical match
            overlaps = any(
                m.start() <= match.start() < m.end() or
                m.start() < match.end() <= m.end()
                for m in author_year_matches
            )
            if not overlaps:
                context = _extract_context(text, match.start(), match.end(), context_chars)
                citation = InTextCitation(
                    text=match.group(0),
                    start_pos=match.start(),
                    end_pos=match.end(),
                    citation_type=CitationType.AUTHOR_YEAR_INLINE,
                    reference_ids=[_make_ref_id(match.group(1), match.group(2))],
                    context=context,
                )
                citations.append(citation)

    # Sort by position
    citations.sort(key=lambda c: c.start_pos)

    return DetectionResult(
        in_text_citations=citations,
        references=[],  # Populated separately
        detected_type=detected_type,
    )


def _extract_context(text: str, start: int, end: int, context_chars: int) -> str:
    """Extract surrounding context for a citation."""
    # Get text before and after the citation
    context_start = max(0, start - context_chars)
    context_end = min(len(text), end + context_chars)

    # Try to start/end at word boundaries
    if context_start > 0:
        # Find the start of the current word or next word
        while context_start > 0 and text[context_start] not in ' \n\t':
            context_start -= 1
        context_start += 1  # Move past the space

    if context_end < len(text):
        # Find the end of the current word
        while context_end < len(text) and text[context_end] not in ' \n\t':
            context_end += 1

    context = text[context_start:context_end]

    # Clean up whitespace
    context = ' '.join(context.split())

    return context


def parse_references(reference_entries: list[str]) -> list[Citation]:
    """
    Parse reference entries into structured Citation objects.

    Args:
        reference_entries: List of reference text strings

    Returns:
        List of parsed Citation objects
    """
    citations: list[Citation] = []

    for idx, entry in enumerate(reference_entries):
        citation = _parse_single_reference(entry, idx)
        citations.append(citation)

    return citations


def _parse_single_reference(entry: str, idx: int) -> Citation:
    """Parse a single reference entry."""
    entry = entry.strip()

    # Try to extract DOI if present
    doi = _extract_doi(entry)
    doi_url = f"https://doi.org/{doi}" if doi else None

    # Try to find year anywhere in the text first
    year_match = re.search(r'\b(19|20)\d{2}\b', entry)
    year = int(year_match.group(0)) if year_match else None

    # Try author-year format (APA): Smith, J. (2020). Title...
    match = AUTHOR_YEAR_REF_PATTERN.match(entry)
    if match:
        authors = _parse_authors(match.group("authors"))
        year = int(match.group("year")[:4])
        title = match.group("title").strip()

        return Citation(
            id=_make_ref_id(authors[0] if authors else f"ref{idx}", str(year)),
            raw_text=entry,
            authors=authors,
            title=title,
            year=year,
            doi=doi,
            doi_url=doi_url,
        )

    # Try Harvard style (year without parentheses): Smith, J., 2020. Title...
    match = HARVARD_REF_PATTERN.match(entry)
    if match:
        authors = _parse_authors(match.group("authors"))
        year = int(match.group("year")[:4])
        remainder = match.group("remainder").strip()

        # Parse the remainder into title, journal, volume, issue, pages
        title, journal, volume, issue, pages = _parse_harvard_remainder(remainder)

        return Citation(
            id=_make_ref_id(authors[0] if authors else f"ref{idx}", str(year)),
            raw_text=entry,
            authors=authors,
            title=title,
            year=year,
            journal=journal,
            volume=volume,
            issue=issue,
            pages=pages,
            doi=doi,
            doi_url=doi_url,
        )

    # Try Vancouver/medical style: Smith J, Jones B. Title. Journal 2020;...
    match = VANCOUVER_REF_PATTERN.match(entry)
    if match:
        authors = _parse_vancouver_authors(match.group("authors"))
        title = match.group("title").strip()

        # Extract journal, volume, issue, pages from remaining text
        journal, volume, issue, pages = _extract_vancouver_metadata(entry, match.end())

        return Citation(
            id=_make_ref_id(authors[0] if authors else f"ref{idx}", str(year) if year else ""),
            raw_text=entry,
            authors=authors,
            title=title,
            year=year,
            journal=journal,
            volume=volume,
            issue=issue,
            pages=pages,
            doi=doi,
            doi_url=doi_url,
        )

    # Try numbered format: 1. Smith J. Title...
    match = NUMBERED_REF_PATTERN.match(entry)
    if match:
        authors = _parse_authors(match.group("authors"))
        title = match.group("title").strip()

        return Citation(
            id=str(idx + 1),
            raw_text=entry,
            authors=authors,
            title=title,
            year=year,
            doi=doi,
            doi_url=doi_url,
        )

    # Fallback: try to extract authors from beginning of entry
    authors = _extract_authors_fallback(entry)

    return Citation(
        id=_make_ref_id(authors[0] if authors else f"ref{idx}", str(year) if year else ""),
        raw_text=entry,
        authors=authors,
        year=year,
        doi=doi,
        doi_url=doi_url,
    )


def _parse_authors(author_string: str) -> list[str]:
    """Parse author string into list of author names."""
    author_string = author_string.strip().rstrip(",")

    # First, try Harvard-style parsing: "LastName, Initials., LastName2, Initials2."
    # This handles formats like "Salthouse, T.A., Babcock, R.L." or "Cohen, S., & Hoberman, H. M."
    harvard_authors = _parse_harvard_authors(author_string)
    if harvard_authors:
        return harvard_authors

    # Split on common separators
    if " & " in author_string:
        authors = author_string.split(" & ")
    elif " and " in author_string.lower():
        authors = re.split(r'\s+and\s+', author_string, flags=re.IGNORECASE)
    elif ", " in author_string and author_string.count(",") > 1:
        # Multiple authors separated by commas
        authors = author_string.split(", ")
    else:
        authors = [author_string]

    return [a.strip() for a in authors if a.strip()]


def _parse_harvard_authors(author_string: str) -> list[str]:
    """
    Parse Harvard-style author string where format is "LastName, Initials".

    Examples:
    - "Salthouse, T.A., Babcock, R.L." -> ["Salthouse, T.A.", "Babcock, R.L."]
    - "Cohen, S., & Hoberman, H. M." -> ["Cohen, S.", "Hoberman, H. M."]
    - "Smith, J., Jones, B., & Williams, C." -> ["Smith, J.", "Jones, B.", "Williams, C."]

    Returns:
        List of authors, or empty list if not Harvard format
    """
    # Remove trailing punctuation
    author_string = author_string.strip().rstrip(",.")

    # Check if this looks like Harvard format: should have "LastName, Initials" pattern
    # Initials are typically 1-4 uppercase letters with optional periods
    initials_pattern = r'[A-Z]\.?\s*[A-Z]?\.?\s*[A-Z]?\.?\s*[A-Z]?\.?'

    # Split by " & " first to handle last author
    parts = re.split(r'\s*&\s*', author_string)

    authors = []
    for part in parts:
        part = part.strip().rstrip(",")
        if not part:
            continue

        # Now split this part into individual "LastName, Initials" pairs
        # Pattern: Look for "Word(s), Initials" where initials are short uppercase sequences
        # Use regex to find all "LastName, Initials" patterns
        author_pattern = re.compile(
            r'([A-Z][a-zA-Z\'\-]+(?:\s+[a-z]+)?(?:\s+[A-Z][a-zA-Z\'\-]+)*),\s*([A-Z]\.?\s*(?:[A-Z]\.?\s*)*)'
        )

        matches = author_pattern.findall(part)
        if matches:
            for last_name, initials in matches:
                initials = initials.strip().rstrip(",")
                authors.append(f"{last_name}, {initials}")
        elif part:
            # If no pattern match but part exists, it might be a single name
            # Check if it looks like "LastName, Initials"
            if re.match(r'^[A-Z][a-zA-Z\'\-]+,\s*[A-Z]', part):
                authors.append(part)

    # Return parsed authors only if we found valid Harvard-style entries
    if authors and len(authors) >= 1:
        return authors

    return []


def _parse_vancouver_authors(author_string: str) -> list[str]:
    """Parse Vancouver-style author string (LastName Initials, LastName Initials)."""
    author_string = author_string.strip().rstrip(",.")

    # Vancouver format: "Smith J, Jones AB, Williams CD"
    # Split on comma, each part is "LastName Initials"
    parts = author_string.split(",")
    authors = []

    for part in parts:
        part = part.strip()
        if part:
            # Extract just the last name (first word)
            words = part.split()
            if words:
                # Keep the full "LastName Initials" format
                authors.append(part)

    return authors


def _extract_authors_fallback(entry: str) -> list[str]:
    """Fallback author extraction from the beginning of a reference."""
    # Try to find authors before the first period that's followed by a capital letter
    # This handles: "Smith J, Jones B. Title here..."

    # Look for pattern: words at start, ending with period before title
    match = re.match(r'^([^.]+)\.', entry)
    if not match:
        return []

    potential_authors = match.group(1)

    # Check if this looks like author names (contains capital letters, possibly commas)
    # and not a title (usually longer)
    if len(potential_authors) < 100 and re.search(r'[A-Z][a-z]+\s+[A-Z]', potential_authors):
        # Looks like Vancouver style
        return _parse_vancouver_authors(potential_authors)

    return []


def _make_ref_id(author: str, year: str) -> str:
    """Create a reference ID from author and year."""
    # Extract last name
    author = author.strip()
    if "," in author:
        last_name = author.split(",")[0]
    else:
        parts = author.split()
        last_name = parts[0] if parts else author

    # Clean up
    last_name = re.sub(r'[^a-zA-Z\'-]', '', last_name) # Keep hyphens and apostrophes
    year = re.sub(r'[^0-9a-z]', '', year)

    return f"{last_name.lower()}_{year}"


def _parse_numeric_refs(ref_string: str) -> list[str]:
    """Parse numeric reference string like '1, 2, 3' or '1-3' into list."""
    refs: list[str] = []
    parts = re.split(r'\s*,\s*', ref_string)

    for part in parts:
        if '-' in part:
            # Range: 1-3 -> [1, 2, 3]
            try:
                start, end = part.split('-')
                refs.extend(str(i) for i in range(int(start), int(end) + 1))
            except ValueError:
                refs.append(part.strip())
        else:
            refs.append(part.strip())

    return refs


def _extract_vancouver_metadata(entry: str, title_end: int) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Extract journal, volume, issue, pages from Vancouver-style reference.

    Args:
        entry: Full reference text
        title_end: Position where title ends

    Returns:
        Tuple of (journal, volume, issue, pages)
    """
    # Get text after title
    remaining = entry[title_end:].strip()

    journal = None
    volume = None
    issue = None
    pages = None

    # Vancouver format: "Journal Name Year;Volume(Issue):Pages."
    # Or: "Journal Name. Year;Volume(Issue):Pages."
    # Or with dates: "Journal Name. 2017 Apr 14;7(4):41."

    # Remove DOI and URL from end
    remaining = re.sub(r'\s*(?:doi[:\s]*)?(?:https?://)?(?:dx\.)?doi\.org/\S+', '', remaining, flags=re.IGNORECASE)
    remaining = re.sub(r'\s*https?://\S+', '', remaining)

    # Pages pattern: handles ranges (181-205), single numbers (41, 106034),
    # article numbers (e00205), and prefixed pages (S264-S271)
    pages_pattern = r'[eS]?\d+(?:[-–][eS]?\d+)?'

    # Try to find volume(issue):pages pattern
    # Issue can be alphanumeric (S7, Suppl 1, etc.)
    vol_pattern = re.search(r'(\d+)\s*\(([^)]+)\)\s*[:\.]?\s*(' + pages_pattern + r')', remaining)
    if vol_pattern:
        volume = vol_pattern.group(1)
        issue = vol_pattern.group(2)
        pages = vol_pattern.group(3).replace('–', '-')

        # Journal is text before the year/volume pattern
        before_vol = remaining[:vol_pattern.start()]
        # Remove year (with optional month/day) from journal text
        before_vol = re.sub(r'\b(19|20)\d{2}(?:\s+[A-Z][a-z]{2,8}(?:\s+\d{1,2})?)?[;.\s]*$', '', before_vol)
        before_vol = before_vol.strip(' .;')
        if before_vol:
            journal = before_vol

    else:
        # Try pattern: Volume:Pages (no issue)
        simple_vol = re.search(r';(\d+)\s*:\s*(' + pages_pattern + r')', remaining)
        if simple_vol:
            volume = simple_vol.group(1)
            pages = simple_vol.group(2).replace('–', '-')
            before_vol = remaining[:simple_vol.start()]
            before_vol = re.sub(r'\b(19|20)\d{2}(?:\s+[A-Z][a-z]{2,8}(?:\s+\d{1,2})?)?[;.\s]*$', '', before_vol)
            before_vol = before_vol.strip(' .;')
            if before_vol:
                journal = before_vol
        else:
            # Try pattern: Volume(Issue) without explicit pages separator
            # e.g., "2017;7(4):41" or "2005;53(S7):S264-S271"
            vol_issue_pattern = re.search(r';(\d+)\s*\(([^)]+)\)\s*[:\.]?\s*(' + pages_pattern + r')?', remaining)
            if vol_issue_pattern:
                volume = vol_issue_pattern.group(1)
                issue = vol_issue_pattern.group(2)
                if vol_issue_pattern.group(3):
                    pages = vol_issue_pattern.group(3).replace('–', '-')
                before_vol = remaining[:vol_issue_pattern.start()]
                before_vol = re.sub(r'\b(19|20)\d{2}(?:\s+[A-Z][a-z]{2,8}(?:\s+\d{1,2})?)?[;.\s]*$', '', before_vol)
                before_vol = before_vol.strip(' .;')
                if before_vol:
                    journal = before_vol

    # If no volume pattern found, try to get journal name before year
    if not journal:
        year_match = re.search(r'\b(19|20)\d{2}\b', remaining)
        if year_match:
            before_year = remaining[:year_match.start()].strip(' .;')
            if before_year and len(before_year) > 2:
                journal = before_year

    return journal, volume, issue, pages


def _parse_harvard_remainder(remainder: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Parse Harvard-style reference remainder into title, journal, volume, issue, pages.

    The remainder after "Authors, Year." contains: "Title. Journal, Volume(Issue), Pages."

    Examples:
    - "The biology of the human–animal bond. Anim. Front. 4(3), 32–36."
    - "Advanced Normalization Tools: V1.0. The Insight J., 2, 1-35."
    - "Title with Oxytocin. Front. Psychol., 3."

    Returns:
        Tuple of (title, journal, volume, issue, pages)
    """
    # Remove DOI from the end first
    remainder = re.sub(r'\s*(?:doi[:\s]*)?(?:https?://)?(?:dx\.)?doi\.org/\S+', '', remainder, flags=re.IGNORECASE)
    remainder = re.sub(r'\s*https?://\S+', '', remainder)
    remainder = remainder.strip()

    if not remainder:
        return None, None, None, None, None

    # Strategy: Find the volume/pages pattern at the end, then work backwards
    # Volume patterns to look for:
    # - "Volume(Issue), Pages" e.g., "4(3), 32-36"
    # - "Volume, Pages" e.g., "63, 235-248"
    # - "Volume(Issue)" e.g., "3" (article number, no pages)
    # - ", Pages" e.g., ", 1-8" (just pages, no volume)

    title = None
    journal = None
    volume = None
    issue = None
    pages = None

    # Pattern 1: Volume(Issue), Pages - e.g., "4(3), 32–36"
    vol_issue_pages = re.search(
        r'[,.\s]\s*(\d+)\s*\(([^)]+)\)\s*,?\s*(\d+[-–]\d+|\d+)\s*\.?\s*$',
        remainder
    )

    # Pattern 2: Volume, Pages (no issue) - e.g., "63, 235-248" or "2, 1-35"
    vol_pages = re.search(
        r'[,.\s]\s*(\d+)\s*,\s*(\d+[-–]\d+|\d+)\s*\.?\s*$',
        remainder
    )

    # Pattern 3: Just Volume (article number) - e.g., ", 3." at end
    just_vol = re.search(
        r'[,.\s]\s*(\d+)\s*\.?\s*$',
        remainder
    )

    # Pattern 4: Just Pages (no volume) - e.g., ", 1–8."
    just_pages = re.search(
        r',\s*(\d+[-–]\d+)\s*\.?\s*$',
        remainder
    )

    # Choose the best matching pattern
    match_end = len(remainder)

    if vol_issue_pages:
        volume = vol_issue_pages.group(1)
        issue = vol_issue_pages.group(2)
        pages = vol_issue_pages.group(3).replace('–', '-')
        match_end = vol_issue_pages.start()
    elif vol_pages:
        volume = vol_pages.group(1)
        pages = vol_pages.group(2).replace('–', '-')
        match_end = vol_pages.start()
    elif just_pages:
        pages = just_pages.group(1).replace('–', '-')
        match_end = just_pages.start()
    elif just_vol:
        volume = just_vol.group(1)
        match_end = just_vol.start()

    # Now split the remaining text into title and journal
    # The journal name is just before the volume/pages
    before_vol = remainder[:match_end].strip(' ,.')

    if before_vol:
        # Strategy: Find where the title ends and journal begins
        # Titles end with ". " followed by journal name
        # Journal names can contain periods (abbreviations like "J.", "Psychol.")
        # Key: Journal name is typically short (<50 chars) and at the end before volume

        # Find all ". " positions (potential title ends)
        # We want the split where the journal part looks like a journal name
        split_candidates = []
        for m in re.finditer(r'\.\s+', before_vol):
            pos = m.start()
            potential_title = before_vol[:pos + 1].strip()
            potential_journal = before_vol[m.end():].strip(' .')

            if potential_journal:
                # Score this split based on how "journal-like" the journal part is
                # Good signs: short, contains abbreviations, starts with capital
                # Bad signs: contains lowercase words like "the", "of", "and", "in"

                score = 0

                # Shorter is better for journals (usually < 40 chars)
                if len(potential_journal) < 40:
                    score += 3
                elif len(potential_journal) < 60:
                    score += 1

                # Journal abbreviations often have periods (J., Psychol., etc.)
                if re.search(r'\b[A-Z][a-z]*\.', potential_journal):
                    score += 2

                # Penalize if starts with lowercase (rare for journals)
                if potential_journal[0].islower():
                    score -= 3

                # Penalize common title words at the start
                lower_journal = potential_journal.lower()
                if lower_journal.startswith(('the ', 'a ', 'an ')):
                    score -= 2
                if ' the ' in lower_journal or ' of ' in lower_journal:
                    score -= 1

                # Title should be longer than journal typically
                if len(potential_title) > len(potential_journal):
                    score += 1

                # Penalize if title ends with a single letter abbreviation (like "J.")
                # This likely means the abbreviation belongs to the journal, not the title
                if re.search(r'\s[A-Z]\.$', potential_title):
                    score -= 4

                # Penalize if title ends with common journal abbreviation prefixes
                if re.search(r'\s(J|Int|Am|Br|Eur|Ann|Arch|Proc|Trans)\.$', potential_title):
                    score -= 5

                split_candidates.append((pos, m.end(), score, potential_title, potential_journal))

        if split_candidates:
            # Sort by score (descending), then by position (later is better for journal)
            split_candidates.sort(key=lambda x: (x[2], x[0]), reverse=True)
            best = split_candidates[0]
            title = best[3]
            journal = best[4]
        else:
            # No good split found - treat the whole thing as title
            title = before_vol

    return title, journal, volume, issue, pages


def _extract_doi(text: str) -> Optional[str]:
    """Extract DOI from reference text if present."""
    # DOI pattern: 10.xxxx/xxxxx
    doi_pattern = re.compile(
        r'(?:doi[:\s]*)?(?:https?://(?:dx\.)?doi\.org/)?'
        r'(10\.\d{4,}/[^\s\]>]+)',
        re.IGNORECASE
    )
    match = doi_pattern.search(text)
    if match:
        doi = match.group(1)
        # Clean trailing punctuation
        doi = doi.rstrip('.,;')
        return doi
    return None


@dataclass
class FuzzyMatchInfo:
    """Details about a fuzzy match for warning generation."""
    ref_id: str
    citation_author: str
    ref_author: str
    author_is_fuzzy: bool  # True if author name required fuzzy matching
    year_is_fuzzy: bool    # True if year required tolerance
    citation_year: Optional[int] = None
    ref_year: Optional[int] = None


@dataclass
class MatchResult:
    """Result of matching citations to references."""
    matches: dict[str, list[str]]  # Citation text -> list of matched reference IDs
    fuzzy_matches: dict[str, list[FuzzyMatchInfo]]  # Citation text -> list of fuzzy match details


def match_citations_to_references(
    in_text: list[InTextCitation],
    references: list[Citation],
) -> MatchResult:
    """
    Match in-text citations to reference entries using two-pass approach.

    First pass: Exact matches only
    Second pass: Fuzzy matches for remaining (flagged for review)

    Returns:
        MatchResult with exact matches and fuzzy matches tracked separately
    """
    matches: dict[str, list[str]] = {}
    fuzzy_matches: dict[str, list[FuzzyMatchInfo]] = {}

    for citation in in_text:
        matched_refs: list[str] = []
        fuzzy_refs: list[FuzzyMatchInfo] = []

        for ref in references:
            match_detail = _citations_match(citation, ref)

            if match_detail.match_type == MatchType.EXACT:
                matched_refs.append(ref.id)
            elif match_detail.match_type == MatchType.FUZZY:
                matched_refs.append(ref.id)
                # Only track as fuzzy match needing review if author OR year was fuzzy
                # But only generate spelling warning if AUTHOR was fuzzy
                fuzzy_refs.append(FuzzyMatchInfo(
                    ref_id=ref.id,
                    citation_author=match_detail.citation_author,
                    ref_author=match_detail.ref_author,
                    author_is_fuzzy=match_detail.author_is_fuzzy,
                    year_is_fuzzy=match_detail.year_is_fuzzy,
                    citation_year=match_detail.citation_year,
                    ref_year=match_detail.ref_year,
                ))

        matches[citation.text] = matched_refs
        if fuzzy_refs:
            fuzzy_matches[citation.text] = fuzzy_refs

    return MatchResult(matches=matches, fuzzy_matches=fuzzy_matches)


def _normalize_dashes(text: str) -> str:
    """Normalize all dash/hyphen variants to standard hyphen-minus for comparison."""
    # Replace en dash, em dash, figure dash, hyphen, non-breaking hyphen with standard hyphen
    dash_chars = '\u2010\u2011\u2012\u2013\u2014'
    for dash in dash_chars:
        text = text.replace(dash, '-')
    return text


def _normalize_apostrophes(text: str) -> str:
    """Normalize all apostrophe variants to standard ASCII apostrophe for comparison."""
    # Replace right single quote, modifier letter apostrophe with standard apostrophe
    apos_chars = '\u2019\u02BC'
    for apos in apos_chars:
        text = text.replace(apos, "'")
    return text


def _normalize_for_matching(text: str) -> str:
    """Normalize dashes and apostrophes for consistent matching."""
    return _normalize_apostrophes(_normalize_dashes(text))


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein distance between two strings for fuzzy matching."""
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


def _fuzzy_author_match(citation_author: str, ref_author: str) -> MatchType:
    """
    Check if author names match, distinguishing exact from fuzzy matches.

    Args:
        citation_author: Author name from in-text citation (lowercase)
        ref_author: Author name from reference (lowercase)

    Returns:
        MatchType indicating EXACT, FUZZY, or NONE
    """
    # Normalize dashes and apostrophes for comparison (Word often uses en dash or curly quotes)
    citation_author = _normalize_for_matching(citation_author)
    ref_author = _normalize_for_matching(ref_author)

    # Exact match
    if citation_author == ref_author:
        return MatchType.EXACT

    # Substring match - check if it's a small difference (likely typo) or large (legitimate)
    if citation_author in ref_author or ref_author in citation_author:
        len_diff = abs(len(citation_author) - len(ref_author))
        if len_diff <= 2:
            # Small difference suggests typo (e.g., "Ficek-Tani" vs "Ficek-Tania")
            return MatchType.FUZZY
        # Large difference is likely legitimate (e.g., compound names)
        return MatchType.EXACT

    # Fuzzy match for typos - allow 1-2 character differences based on name length
    max_distance = 1 if len(citation_author) <= 6 else 2
    distance = _levenshtein_distance(citation_author, ref_author)

    if distance <= max_distance:
        return MatchType.FUZZY

    return MatchType.NONE


def _citations_match(in_text: InTextCitation, reference: Citation, year_tolerance: int = 1) -> CitationMatchDetail:
    """
    Check if an in-text citation matches a reference.

    Args:
        in_text: The in-text citation
        reference: The reference to compare against
        year_tolerance: Allow years to differ by this many years (default 1)

    Returns:
        CitationMatchDetail with match type and details about what was fuzzy
    """
    if in_text.citation_type == CitationType.NUMERIC:
        # Numeric: check if reference ID is in the citation's reference_ids
        if reference.id in in_text.reference_ids:
            return CitationMatchDetail(match_type=MatchType.EXACT)
        return CitationMatchDetail(match_type=MatchType.NONE)

    # Author-year: extract authors and year from the citation text directly
    citation_text = in_text.text

    # Extract citation author names and year (already lowercased)
    citation_authors_list = _extract_citation_authors(citation_text)

    # Extract year from citation
    year_match = re.search(r'\b(19|20)\d{2}[a-z]?\b', citation_text)
    citation_year = int(year_match.group(0)[:4]) if year_match else None

    # Get last names from reference authors (lowercased and normalized)
    ref_last_names = []
    for author in reference.authors:
        last_name = _extract_last_name(author)
        if last_name:
            ref_last_names.append(_normalize_for_matching(last_name.lower()))

    reference_year = reference.year

    if not citation_authors_list or not ref_last_names:
        return CitationMatchDetail(match_type=MatchType.NONE)

    # Track if any part of the match is fuzzy, and which author had the mismatch
    author_is_fuzzy = False
    fuzzy_citation_author = ""
    fuzzy_ref_author = ""

    # Author matching: Citation's FIRST author must match reference's FIRST author
    citation_first_author = citation_authors_list[0]
    ref_first_author = ref_last_names[0]

    first_author_match = _fuzzy_author_match(citation_first_author, ref_first_author)
    if first_author_match == MatchType.NONE:
        return CitationMatchDetail(match_type=MatchType.NONE)
    if first_author_match == MatchType.FUZZY:
        author_is_fuzzy = True
        fuzzy_citation_author = citation_first_author
        fuzzy_ref_author = ref_first_author

    # For two-author citations (Smith & Jones), also verify second author matches
    if len(citation_authors_list) == 2 and len(ref_last_names) >= 2:
        citation_second_author = citation_authors_list[1]
        ref_second_author = ref_last_names[1]
        second_author_match = _fuzzy_author_match(citation_second_author, ref_second_author)
        if second_author_match == MatchType.NONE:
            return CitationMatchDetail(match_type=MatchType.NONE)
        if second_author_match == MatchType.FUZZY:
            author_is_fuzzy = True
            # Only update if first author wasn't already fuzzy (prioritize showing actual mismatch)
            if not fuzzy_citation_author:
                fuzzy_citation_author = citation_second_author
                fuzzy_ref_author = ref_second_author

    # Check year match - allow tolerance for minor year discrepancies
    year_match_ok = False
    year_is_fuzzy = False

    if citation_year and reference_year:
        year_diff = abs(citation_year - reference_year)
        if year_diff == 0:
            year_match_ok = True
        elif year_diff <= year_tolerance:
            year_match_ok = True
            year_is_fuzzy = True  # Year matched but not exactly
    elif citation_year and not reference_year:
        year_match_ok = True
    elif not citation_year and reference_year:
        year_match_ok = True
    elif not citation_year and not reference_year:
        year_match_ok = True

    if not year_match_ok:
        return CitationMatchDetail(match_type=MatchType.NONE)

    # Determine overall match type
    if author_is_fuzzy or year_is_fuzzy:
        match_type = MatchType.FUZZY
    else:
        match_type = MatchType.EXACT

    return CitationMatchDetail(
        match_type=match_type,
        author_is_fuzzy=author_is_fuzzy,
        year_is_fuzzy=year_is_fuzzy,
        # Use the actual mismatched author names, or first author if no mismatch
        citation_author=fuzzy_citation_author if fuzzy_citation_author else citation_first_author,
        ref_author=fuzzy_ref_author if fuzzy_ref_author else ref_first_author,
        citation_year=citation_year,
        ref_year=reference_year,
    )


def _extract_citation_authors(citation_text: str) -> list[str]:
    """Extract author names from in-text citation like (Smith & Jones, 2020)."""
    # Remove parentheses and year
    text = re.sub(r'[()]', '', citation_text)
    text = re.sub(r',?\s*\d{4}[a-z]?', '', text)
    text = text.strip()

    # Handle "et al." and "and colleagues" (both mean multiple authors)
    text = re.sub(r'\s+et\s+al\.?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+and\s+colleagues', '', text, flags=re.IGNORECASE)

    # Split on & or "and" (but not "and colleagues" which was already removed)
    if ' & ' in text:
        authors = text.split(' & ')
    elif ' and ' in text.lower():
        authors = re.split(r'\s+and\s+', text, flags=re.IGNORECASE)
    else:
        authors = [text]

    # Return lowercased and normalized for consistent comparison
    return [_normalize_for_matching(a.strip().lower()) for a in authors if a.strip()]


def _extract_last_name(author: str) -> str:
    """Extract last name from various author formats."""
    author = author.strip()

    # Handle cases where reference author list might include "et al." directly
    # e.g., "LeBlanc J et al."
    if author.lower().endswith(' et al.'):
        author = author[:-len(' et al.')].strip()

    # Format: "Smith, John" or "Smith, J."
    if "," in author:
        return author.split(",")[0].strip()

    parts = author.split()
    if len(parts) >= 2:
        last_part = parts[-1]

        # Check if last part looks like initials (Vancouver style: "Smith JA")
        # Initials are: 1-4 chars, ALL uppercase, optional periods
        is_initials = (
            len(last_part.replace(".", "")) <= 4 and
            last_part.replace(".", "").isupper() and
            last_part.replace(".", "").isalpha()
        )

        if is_initials:
            # Vancouver style: first part(s) are last name
            # Handle multi-word last names: "Van der Berg JA" -> "Van der Berg"
            return " ".join(parts[:-1])
        else:
            # Standard style: "John Smith" -> "Smith" (last word is last name)
            return last_part

    elif parts:
        return parts[0]

    return author
