"""Bibliography export service for BibTeX and RIS formats."""

import re
from typing import Optional

from app.models.schemas import Citation, BibFormat, ExportResult


def export_references(
    references: list[Citation],
    format: BibFormat = BibFormat.BIBTEX,
) -> ExportResult:
    """
    Export references to bibliography format.

    Args:
        references: List of Citation objects
        format: Target format (BibTeX or RIS)

    Returns:
        ExportResult with formatted content
    """
    warnings = []

    if format == BibFormat.BIBTEX:
        content, warnings = _export_bibtex(references)
    elif format == BibFormat.RIS:
        content, warnings = _export_ris(references)
    else:
        raise ValueError(f"Unsupported format: {format}")

    return ExportResult(
        format=format,
        content=content,
        entry_count=len(references),
        warnings=warnings,
    )


def _export_bibtex(references: list[Citation]) -> tuple[str, list[str]]:
    """
    Export references to BibTeX format.

    Returns:
        Tuple of (content, warnings)
    """
    entries = []
    warnings = []
    used_keys: set[str] = set()

    for ref in references:
        entry, entry_warnings, key = _citation_to_bibtex(ref, used_keys)
        entries.append(entry)
        warnings.extend(entry_warnings)
        used_keys.add(key)

    return "\n\n".join(entries), warnings


def _citation_to_bibtex(
    ref: Citation,
    used_keys: set[str],
) -> tuple[str, list[str], str]:
    """
    Convert a single Citation to BibTeX entry.

    Returns:
        Tuple of (entry_string, warnings, citation_key)
    """
    warnings = []

    # Generate citation key
    key = _make_bibtex_key(ref, used_keys)

    # Determine entry type
    entry_type = "article"  # Default to journal article

    lines = [f"@{entry_type}{{{key},"]

    # Authors
    if ref.authors:
        authors_str = " and ".join(_format_bibtex_author(a) for a in ref.authors)
        lines.append(f"  author = {{{authors_str}}},")
    else:
        warnings.append(f"{key}: missing authors")

    # Title (double braces preserve case)
    if ref.title:
        # Escape special LaTeX characters
        title = _escape_latex(ref.title)
        lines.append(f"  title = {{{{{title}}}}},")
    else:
        warnings.append(f"{key}: missing title")

    # Year
    if ref.year:
        lines.append(f"  year = {{{ref.year}}},")
    else:
        warnings.append(f"{key}: missing year")

    # Journal
    if ref.journal:
        journal = _escape_latex(ref.journal)
        lines.append(f"  journal = {{{journal}}},")

    # Volume
    if ref.volume:
        lines.append(f"  volume = {{{ref.volume}}},")

    # Number/Issue
    if ref.issue:
        lines.append(f"  number = {{{ref.issue}}},")

    # Pages
    if ref.pages:
        # Normalize page ranges to use --
        pages = ref.pages.replace("-", "--").replace("---", "--")
        lines.append(f"  pages = {{{pages}}},")

    # DOI
    if ref.doi:
        lines.append(f"  doi = {{{ref.doi}}},")

    lines.append("}")

    return "\n".join(lines), warnings, key


def _make_bibtex_key(ref: Citation, used_keys: set[str]) -> str:
    """Generate a unique BibTeX citation key."""
    author_part = ""
    if ref.authors:
        # Get first author's last name
        author = ref.authors[0]
        if "," in author:
            author_part = author.split(",")[0]
        else:
            parts = author.split()
            author_part = parts[-1] if parts else author
        # Remove non-alphanumeric characters
        author_part = re.sub(r'[^a-zA-Z]', '', author_part)

    year_part = str(ref.year) if ref.year else ""

    base_key = f"{author_part}{year_part}".lower()

    # Ensure uniqueness
    if base_key not in used_keys:
        return base_key

    # Add suffix for duplicates
    suffix = 'a'
    while f"{base_key}{suffix}" in used_keys:
        suffix = chr(ord(suffix) + 1)

    return f"{base_key}{suffix}"


def _format_bibtex_author(author: str) -> str:
    """Format author name for BibTeX (Last, First)."""
    author = author.strip()
    if "," in author:
        return author  # Already in correct format

    parts = author.split()
    if len(parts) >= 2:
        # Check if last part is initials (Vancouver style: "Smith JA")
        last_part = parts[-1]
        if len(last_part) <= 3 and last_part.replace(".", "").isupper():
            # Vancouver style: join remaining as last name
            return f"{' '.join(parts[:-1])}, {last_part}"
        else:
            # Standard style: last word is last name
            return f"{parts[-1]}, {' '.join(parts[:-1])}"

    return author


def _escape_latex(text: str) -> str:
    """Escape special LaTeX characters."""
    replacements = [
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _export_ris(references: list[Citation]) -> tuple[str, list[str]]:
    """
    Export references to RIS format.

    Returns:
        Tuple of (content, warnings)
    """
    entries = []
    warnings = []

    for ref in references:
        entry, entry_warnings = _citation_to_ris(ref)
        entries.append(entry)
        warnings.extend(entry_warnings)

    return "\n".join(entries), warnings


def _citation_to_ris(ref: Citation) -> tuple[str, list[str]]:
    """
    Convert a single Citation to RIS entry.

    Returns:
        Tuple of (entry_string, warnings)
    """
    warnings = []
    lines = ["TY  - JOUR"]  # Type: Journal Article

    # Authors (AU tag)
    if ref.authors:
        for author in ref.authors:
            lines.append(f"AU  - {author}")
    else:
        warnings.append(f"{ref.id}: missing authors")

    # Title (TI tag)
    if ref.title:
        lines.append(f"TI  - {ref.title}")
    else:
        warnings.append(f"{ref.id}: missing title")

    # Year (PY tag)
    if ref.year:
        lines.append(f"PY  - {ref.year}")
    else:
        warnings.append(f"{ref.id}: missing year")

    # Journal (JO tag for full name, T2 for alternate)
    if ref.journal:
        lines.append(f"JO  - {ref.journal}")

    # Volume (VL tag)
    if ref.volume:
        lines.append(f"VL  - {ref.volume}")

    # Issue (IS tag)
    if ref.issue:
        lines.append(f"IS  - {ref.issue}")

    # Pages (SP for start page, EP for end page)
    if ref.pages:
        # Handle various page formats
        pages = ref.pages.replace("–", "-").replace("—", "-")
        if "-" in pages:
            parts = pages.split("-", 1)
            lines.append(f"SP  - {parts[0].strip()}")
            if len(parts) > 1 and parts[1].strip():
                lines.append(f"EP  - {parts[1].strip()}")
        else:
            lines.append(f"SP  - {pages}")

    # DOI (DO tag)
    if ref.doi:
        lines.append(f"DO  - {ref.doi}")

    # URL from DOI
    if ref.doi_url:
        lines.append(f"UR  - {ref.doi_url}")

    # End of record
    lines.append("ER  - ")
    lines.append("")  # Blank line between records

    return "\n".join(lines), warnings


def export_to_file(
    references: list[Citation],
    file_path: str,
    format: BibFormat = BibFormat.BIBTEX,
) -> ExportResult:
    """
    Export references to a file.

    Args:
        references: List of Citation objects
        file_path: Path to output file
        format: Target format

    Returns:
        ExportResult with formatted content
    """
    result = export_references(references, format)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(result.content)

    return result
