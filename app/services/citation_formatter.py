"""Citation formatting service for reformatting citations to a consistent style."""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.models.schemas import Citation, CitationStyle


@dataclass
class FormatPattern:
    """Learned pattern for citation formatting."""
    author_format: str       # e.g., "LastName, F. M." or "LastName FM"
    author_separator: str    # e.g., ", " or "; "
    author_final_sep: str    # e.g., ", & " or " and "
    year_position: str       # "after_authors" (APA) or "after_journal" (Vancouver)
    year_format: str         # e.g., "(YYYY)" or "YYYY"
    title_style: str         # e.g., "sentence" or "title"
    title_quotes: bool       # Whether article titles are in quotes
    title_italic: bool       # Whether book/journal titles are italic
    journal_italic: bool
    # Journal/volume/pages grouping: how these elements are combined
    # e.g., "{journal} {year};{volume}:{pages}" for Vancouver
    # or separate parts for APA style
    journal_volume_format: str  # e.g., "{journal} {year};{volume}:{pages}" or ""
    volume_format: str       # e.g., "V(I)" or "V, I" - used when not grouped
    pages_format: str        # e.g., "pp. X-Y" or "X-Y" - used when not grouped
    doi_format: str          # e.g., "https://doi.org/DOI" or "doi:DOI"


# Built-in style templates
STYLE_TEMPLATES: dict[CitationStyle, FormatPattern] = {
    CitationStyle.APA: FormatPattern(
        author_format="{last}, {first_init}.",
        author_separator=", ",
        author_final_sep=", & ",
        year_position="after_authors",
        year_format="({year})",
        title_style="sentence",
        title_quotes=False,
        title_italic=False,
        journal_italic=True,
        journal_volume_format="",  # APA uses separate parts
        volume_format="{volume}({issue})",
        pages_format="{pages}",
        doi_format="https://doi.org/{doi}",
    ),
    CitationStyle.MLA: FormatPattern(
        author_format="{last}, {first}",
        author_separator=", ",
        author_final_sep=", and ",
        year_position="after_authors",
        year_format="{year}",
        title_style="title",
        title_quotes=True,
        title_italic=False,
        journal_italic=True,
        journal_volume_format="",
        volume_format="vol. {volume}, no. {issue}",
        pages_format="pp. {pages}",
        doi_format="doi:{doi}",
    ),
    CitationStyle.CHICAGO: FormatPattern(
        author_format="{last}, {first}",
        author_separator=", ",
        author_final_sep=", and ",
        year_position="after_authors",
        year_format="{year}",
        title_style="title",
        title_quotes=True,
        title_italic=False,
        journal_italic=True,
        journal_volume_format="",
        volume_format="{volume}, no. {issue}",
        pages_format="{pages}",
        doi_format="https://doi.org/{doi}",
    ),
    CitationStyle.VANCOUVER: FormatPattern(
        author_format="{last} {first_init}",
        author_separator=", ",
        author_final_sep=", ",
        year_position="after_journal",
        year_format="{year}",
        title_style="sentence",
        title_quotes=False,
        title_italic=False,
        journal_italic=False,
        journal_volume_format="{journal} {year};{volume}:{pages}",  # Vancouver groups these
        volume_format="{volume}({issue})",
        pages_format="{pages}",
        doi_format="https://doi.org/{doi}",
    ),
    CitationStyle.IEEE: FormatPattern(
        author_format="{first_init}. {last}",
        author_separator=", ",
        author_final_sep=", and ",
        year_position="after_authors",
        year_format="{year}",
        title_style="sentence",
        title_quotes=True,
        title_italic=False,
        journal_italic=True,
        journal_volume_format="",
        volume_format="vol. {volume}, no. {issue}",
        pages_format="pp. {pages}",
        doi_format="doi: {doi}",
    ),
}


def learn_format_from_examples(examples: list[str]) -> FormatPattern:
    """
    Learn citation format pattern from example citations.

    Args:
        examples: List of formatted citation strings

    Returns:
        Learned FormatPattern
    """
    if not examples:
        return STYLE_TEMPLATES[CitationStyle.APA]

    # Analyze patterns across examples
    author_formats: list[str] = []
    year_patterns: list[str] = []
    year_positions: list[str] = []
    separators: list[str] = []
    journal_vol_formats: list[str] = []
    has_journal_italic: list[bool] = []

    for example in examples:
        # Detect author format
        author_format = _detect_author_format(example)
        if author_format:
            author_formats.append(author_format)

        # Detect year format and position
        year_pattern, year_pos = _detect_year_pattern_and_position(example)
        if year_pattern:
            year_patterns.append(year_pattern)
        if year_pos:
            year_positions.append(year_pos)

        # Detect separators
        sep = _detect_separators(example)
        if sep:
            separators.append(sep)

        # Detect journal/volume/pages grouping format
        jvf = _detect_journal_volume_format(example)
        if jvf:
            journal_vol_formats.append(jvf)

        # Detect if journals use italics (markdown asterisks)
        has_journal_italic.append('*' in example)

    # Determine if journals should be italic based on examples
    # If NO examples use asterisks, don't use italic
    journal_italic = any(has_journal_italic) if has_journal_italic else False

    # Determine year position
    year_position = _most_common(year_positions, "after_authors")

    # Determine journal/volume format
    journal_volume_format = _most_common(journal_vol_formats, "")

    # Use most common patterns or defaults
    return FormatPattern(
        author_format=_most_common(author_formats, "{last}, {first_init}."),
        author_separator=", ",
        author_final_sep=_most_common(separators, ", & "),
        year_position=year_position,
        year_format=_most_common(year_patterns, "({year})"),
        title_style="sentence",
        title_quotes=any('"' in ex for ex in examples),
        title_italic=False,
        journal_italic=journal_italic,
        journal_volume_format=journal_volume_format,
        volume_format="{volume}({issue})",
        pages_format="{pages}",
        doi_format="https://doi.org/{doi}",
    )


def format_citation(citation: Citation, pattern: FormatPattern) -> str:
    """
    Format a citation according to the given pattern.

    Args:
        citation: Citation object with metadata
        pattern: FormatPattern to apply

    Returns:
        Formatted citation string
    """
    parts: list[str] = []

    # Format authors
    if citation.authors:
        formatted_authors = _format_authors(citation.authors, pattern)
        parts.append(formatted_authors)

    # Format year after authors (if that's the position)
    if citation.year and pattern.year_position == "after_authors":
        year_str = pattern.year_format.format(year=citation.year)
        parts.append(year_str)

    # Format title
    if citation.title:
        title = _format_title(citation.title, pattern.title_style)
        if pattern.title_quotes:
            title = f'"{title}"'
        parts.append(title)

    # Format journal/volume/pages - either grouped or separate
    if pattern.journal_volume_format and citation.journal:
        # Use grouped format (e.g., Vancouver: "Journal Year;Volume:Pages")
        journal_vol_str = _format_journal_volume_group(citation, pattern)
        if journal_vol_str:
            parts.append(journal_vol_str)
    else:
        # Use separate parts (e.g., APA style)
        # Format journal info
        if citation.journal:
            journal = citation.journal
            if pattern.journal_italic:
                journal = f"*{journal}*"  # Markdown italic
            parts.append(journal)

        # Format year after journal (if that's the position and not already added)
        if citation.year and pattern.year_position == "after_journal":
            year_str = pattern.year_format.format(year=citation.year)
            parts.append(year_str)

        # Format volume/issue
        if citation.volume:
            vol_str = pattern.volume_format.format(
                volume=citation.volume,
                issue=citation.issue or "",
            )
            # Clean up empty issue placeholders
            vol_str = re.sub(r'\(\)', '', vol_str)
            vol_str = re.sub(r', no\. $', '', vol_str)
            parts.append(vol_str)

        # Format pages
        if citation.pages:
            pages_str = pattern.pages_format.format(pages=citation.pages)
            parts.append(pages_str)

    # Format DOI
    if citation.doi:
        doi_str = pattern.doi_format.format(doi=citation.doi)
        parts.append(doi_str)

    # Join parts with appropriate separators
    result = ". ".join(parts)

    # Clean up formatting
    # Remove multiple consecutive periods (apply repeatedly for ..., ...., etc.)
    while '..' in result:
        result = re.sub(r'\.\.+', '.', result)
    # Clean up redundant punctuation: "?." -> "?" and "!." -> "!"
    result = re.sub(r'\?\.\s*', '? ', result)
    result = re.sub(r'!\.\s*', '! ', result)
    result = re.sub(r'\s+', ' ', result)       # Normalize spaces

    if not result.endswith('.'):
        result += '.'

    return result


def _format_journal_volume_group(citation: Citation, pattern: FormatPattern) -> str:
    """
    Format journal, year, volume, issue, and pages as a grouped string.

    Used for Vancouver-style citations where these elements are combined:
    e.g., "J Sci Commun 2020;163:51-9" or "Sleep 2006;29(1):85-93"
    """
    # Get journal name (with or without italics)
    journal = citation.journal or ""
    if pattern.journal_italic and journal:
        journal = f"*{journal}*"

    # Build the result manually to handle optional components correctly
    result = journal

    # Add year if present
    if citation.year:
        result += f" {citation.year}"

    # Add volume/issue/pages if any exist
    has_volume_info = citation.volume or citation.pages

    if has_volume_info:
        result += ";"

        # Add volume with optional issue
        if citation.volume:
            result += citation.volume
            if citation.issue:
                result += f"({citation.issue})"

        # Add pages
        if citation.pages:
            if citation.volume:
                result += ":"
            result += citation.pages

    return result.strip()


def format_citations_batch(
    citations: list[Citation],
    style: CitationStyle = CitationStyle.APA,
    examples: Optional[list[str]] = None,
) -> list[str]:
    """
    Format multiple citations.

    Args:
        citations: List of Citation objects
        style: Named style to use (ignored if examples provided)
        examples: Example citations to learn format from

    Returns:
        List of formatted citation strings
    """
    if examples:
        pattern = learn_format_from_examples(examples)
    else:
        pattern = STYLE_TEMPLATES.get(style, STYLE_TEMPLATES[CitationStyle.APA])

    return [format_citation(c, pattern) for c in citations]


def _format_authors(authors: list[str], pattern: FormatPattern) -> str:
    """Format author list according to pattern."""
    if not authors:
        return ""

    formatted: list[str] = []
    for author in authors:
        formatted.append(_format_single_author(author, pattern.author_format))

    if len(formatted) == 1:
        return formatted[0]
    elif len(formatted) == 2:
        return f"{formatted[0]}{pattern.author_final_sep}{formatted[1]}"
    else:
        # Multiple authors: first, second, ..., & last
        all_but_last = pattern.author_separator.join(formatted[:-1])
        return f"{all_but_last}{pattern.author_final_sep}{formatted[-1]}"


def _format_single_author(author: str, format_pattern: str) -> str:
    """Format a single author name."""
    author = author.strip()

    # Parse the author name
    if "," in author:
        # Format: "Smith, John" or "Smith, J."
        parts = author.split(",", 1)
        last = parts[0].strip()
        first = parts[1].strip() if len(parts) > 1 else ""
    else:
        parts = author.split()
        if len(parts) >= 2:
            # Check if this is Vancouver style: "Smith JA" (last name + initials)
            # Initials are typically: all caps, 1-3 chars, no periods between
            last_part = parts[-1]
            is_vancouver = (
                len(last_part) <= 4 and
                last_part.replace(".", "").isupper() and
                not last_part.replace(".", "").islower()
            )

            if is_vancouver:
                # Vancouver style: "Worsley KJ" -> last="Worsley", first_init="KJ"
                # All parts except the last one (which contains initials) form the last name
                # This handles both simple names ("Worsley KJ") and multi-word ("Van der Berg KJ")
                last = " ".join(parts[:-1])
                first = ""
                # The initials are already in last_part
            else:
                # Standard style: "John Smith" -> first="John", last="Smith"
                last = parts[-1]
                first = " ".join(parts[:-1])
        else:
            last = author
            first = ""

    # Generate initials from first name if we have it
    first_init = "".join(
        f"{word[0]}." for word in first.split() if word
    ) if first else ""

    # For Vancouver-style input, extract initials from the original
    if not first_init and not first:
        # Check if original had initials at the end
        parts = author.split()
        if len(parts) >= 2:
            last_part = parts[-1]
            if len(last_part) <= 4 and last_part.replace(".", "").isupper():
                # Format initials properly: "KJ" -> "K.J." or keep as-is
                first_init = ".".join(last_part.replace(".", "")) + "."

    return format_pattern.format(
        last=last,
        first=first,
        first_init=first_init,
    )


def _format_title(title: str, style: str) -> str:
    """Format title according to style (sentence or title case)."""
    if style == "sentence":
        # Sentence case: only first word and proper nouns capitalized
        words = title.split()
        if not words:
            return title
        result = [words[0].capitalize()]
        for word in words[1:]:
            # Keep acronyms and proper nouns
            if word.isupper() or (len(word) > 1 and word[0].isupper()):
                result.append(word)
            else:
                result.append(word.lower())
        return " ".join(result)
    else:
        # Title case
        return title.title()


def _detect_author_format(example: str) -> Optional[str]:
    """Detect author format from example citation."""
    # Look for common patterns at the start
    patterns = [
        (r'^([A-Z][a-z]+),\s+([A-Z])\.\s*([A-Z])?\.?', "{last}, {first_init}."),
        (r'^([A-Z][a-z]+)\s+([A-Z])([A-Z])?\.?', "{last} {first_init}"),
        (r'^([A-Z])\.\s*([A-Z])?\.?\s+([A-Z][a-z]+)', "{first_init}. {last}"),
    ]

    for pattern, format_str in patterns:
        if re.match(pattern, example):
            return format_str

    return None


def _detect_year_pattern(example: str) -> Optional[str]:
    """Detect year formatting pattern."""
    if re.search(r'\(\d{4}\)', example):
        return "({year})"
    elif re.search(r'\d{4}\.', example):
        return "{year}."
    elif re.search(r',\s*\d{4}', example):
        return ", {year}"
    return None


def _detect_year_pattern_and_position(example: str) -> tuple[Optional[str], Optional[str]]:
    """
    Detect year formatting pattern and its position in the citation.

    Returns:
        Tuple of (year_format, year_position)
        year_position is "after_authors" or "after_journal"
    """
    # Look for year in parentheses after authors (APA style)
    # Pattern: Authors (Year). Title.
    if re.search(r'\.\s*\(\d{4}\)\.\s*[A-Z]', example):
        return "({year})", "after_authors"

    # Look for year after journal name followed by semicolon (Vancouver style)
    # Pattern: Title. Journal Year;Volume:Pages
    if re.search(r'\.\s+[A-Za-z\s]+\d{4};\d+', example):
        return "{year}", "after_journal"

    # Look for year followed by semicolon anywhere (likely after journal)
    if re.search(r'\d{4};', example):
        return "{year}", "after_journal"

    # Year with period at end of authors section
    if re.search(r'\)\.\s*\d{4}\.', example):
        return "{year}.", "after_authors"

    # Default detection
    if re.search(r'\(\d{4}\)', example):
        return "({year})", "after_authors"
    elif re.search(r'\d{4}\.', example):
        return "{year}", "after_authors"
    elif re.search(r',\s*\d{4}', example):
        return ", {year}", "after_authors"

    return None, None


def _detect_journal_volume_format(example: str) -> Optional[str]:
    """
    Detect how journal, year, volume, issue, and pages are grouped.

    Common patterns:
    - Vancouver: "Journal Year;Volume(Issue):Pages" or "Journal Year;Volume:Pages"
    - APA: separate parts with periods

    Returns:
        Format string like "{journal} {year};{volume}:{pages}" or empty string
    """
    # Vancouver pattern: Journal Year;Volume(Issue):Pages
    # e.g., "J Sci Commun 2020;163:51–9"
    if re.search(r'[A-Za-z]+\s+\d{4};\d+\([^)]+\):\d+[-–]\d+', example):
        return "{journal} {year};{volume}({issue}):{pages}"

    # Vancouver pattern without issue: Journal Year;Volume:Pages
    # e.g., "J Sci Commun 2020;163:51–9"
    if re.search(r'[A-Za-z]+\s+\d{4};\d+:\d+[-–]\d+', example):
        return "{journal} {year};{volume}:{pages}"

    # Vancouver with just volume (no pages): Journal Year;Volume
    if re.search(r'[A-Za-z]+\s+\d{4};\d+\.', example):
        return "{journal} {year};{volume}"

    # Check for the article number pattern: Journal. Year;Volume:eXXXXX
    if re.search(r'\.\s+\d{4};\d+:e\d+', example):
        return "{journal}. {year};{volume}:{pages}"

    return ""


def _detect_separators(example: str) -> Optional[str]:
    """Detect author separators."""
    if ", & " in example:
        return ", & "
    elif ", and " in example.lower():
        return ", and "
    elif " & " in example:
        return " & "
    elif " and " in example.lower():
        return " and "
    return None


def _most_common(items: list[str], default: str) -> str:
    """Return most common item or default."""
    if not items:
        return default
    from collections import Counter
    counts = Counter(items)
    return counts.most_common(1)[0][0]
