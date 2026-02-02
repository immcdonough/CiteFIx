"""Reference manager import service."""

import json
import re
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz

from app.models.schemas import Citation, ReferenceManagerType, ImportResult


class ReferenceImporter:
    """Import references from reference managers."""

    def import_file(
        self,
        file_path: Path,
        manager_type: ReferenceManagerType,
    ) -> list[Citation]:
        """
        Import references from a file.

        Args:
            file_path: Path to import file
            manager_type: Type of reference manager

        Returns:
            List of Citation objects
        """
        content = file_path.read_text(encoding="utf-8")
        return self.import_content(content, manager_type)

    def import_content(
        self,
        content: str,
        manager_type: ReferenceManagerType,
    ) -> list[Citation]:
        """
        Import references from string content.

        Args:
            content: File content as string
            manager_type: Type of reference manager

        Returns:
            List of Citation objects
        """
        if manager_type == ReferenceManagerType.ZOTERO:
            return self._import_zotero_json(content)
        elif manager_type == ReferenceManagerType.MENDELEY:
            return self._import_bibtex(content)
        elif manager_type == ReferenceManagerType.ENDNOTE:
            return self._import_ris(content)
        else:
            raise ValueError(f"Unsupported manager type: {manager_type}")

    def _import_zotero_json(self, content: str) -> list[Citation]:
        """Import from Zotero JSON export."""
        data = json.loads(content)
        citations = []

        # Handle both array and object formats
        items = data if isinstance(data, list) else data.get("items", [data])

        for idx, item in enumerate(items):
            citation = self._zotero_item_to_citation(item, idx)
            if citation:
                citations.append(citation)

        return citations

    def _zotero_item_to_citation(self, item: dict, idx: int) -> Optional[Citation]:
        """Convert Zotero JSON item to Citation."""
        # Extract authors
        authors = []
        for creator in item.get("creators", []):
            creator_type = creator.get("creatorType", "author")
            if creator_type == "author":
                last_name = creator.get("lastName", "")
                first_name = creator.get("firstName", "")
                if last_name:
                    if first_name:
                        name = f"{last_name}, {first_name}"
                    else:
                        name = last_name
                    authors.append(name)

        # Extract DOI from extra field or DOI field
        doi = item.get("DOI")
        if not doi:
            extra = item.get("extra", "")
            doi_match = re.search(r'DOI:\s*(\S+)', extra, re.IGNORECASE)
            if doi_match:
                doi = doi_match.group(1)

        return Citation(
            id=item.get("key", f"zotero_{idx}"),
            raw_text="",  # Zotero doesn't have raw text
            authors=authors,
            title=item.get("title"),
            year=_extract_year(item.get("date", "")),
            journal=item.get("publicationTitle"),
            volume=item.get("volume"),
            issue=item.get("issue"),
            pages=item.get("pages"),
            doi=doi,
            doi_url=f"https://doi.org/{doi}" if doi else None,
        )

    def _import_bibtex(self, content: str) -> list[Citation]:
        """Import from BibTeX format."""
        try:
            import bibtexparser
            from bibtexparser.bparser import BibTexParser

            parser = BibTexParser(common_strings=True)
            bib_db = bibtexparser.loads(content, parser=parser)

            citations = []
            for entry in bib_db.entries:
                citation = self._bibtex_entry_to_citation(entry)
                if citation:
                    citations.append(citation)

            return citations
        except ImportError:
            # Fallback to simple parsing if bibtexparser not available
            return self._simple_bibtex_parse(content)

    def _bibtex_entry_to_citation(self, entry: dict) -> Citation:
        """Convert BibTeX entry to Citation."""
        # Parse authors
        authors = []
        if "author" in entry:
            # BibTeX uses "and" to separate authors
            author_str = entry["author"]
            authors = [a.strip() for a in author_str.split(" and ")]

        # Clean title (remove braces)
        title = entry.get("title", "")
        title = re.sub(r'[{}]', '', title)

        return Citation(
            id=entry.get("ID", ""),
            raw_text="",
            authors=authors,
            title=title,
            year=_extract_year(entry.get("year", "")),
            journal=entry.get("journal"),
            volume=entry.get("volume"),
            issue=entry.get("number"),
            pages=entry.get("pages"),
            doi=entry.get("doi"),
            doi_url=f"https://doi.org/{entry.get('doi')}" if entry.get("doi") else None,
        )

    def _simple_bibtex_parse(self, content: str) -> list[Citation]:
        """Simple BibTeX parsing without bibtexparser library."""
        citations = []

        # Find all entries
        entry_pattern = re.compile(
            r'@\w+\s*\{\s*([^,]+)\s*,(.+?)\n\s*\}',
            re.DOTALL
        )

        for match in entry_pattern.finditer(content):
            key = match.group(1).strip()
            fields_text = match.group(2)

            # Parse fields
            fields = {}
            field_pattern = re.compile(r'(\w+)\s*=\s*[{"](.+?)[}"]', re.DOTALL)
            for field_match in field_pattern.finditer(fields_text):
                field_name = field_match.group(1).lower()
                field_value = field_match.group(2).strip()
                fields[field_name] = field_value

            # Extract authors
            authors = []
            if "author" in fields:
                authors = [a.strip() for a in fields["author"].split(" and ")]

            citations.append(Citation(
                id=key,
                raw_text="",
                authors=authors,
                title=re.sub(r'[{}]', '', fields.get("title", "")),
                year=_extract_year(fields.get("year", "")),
                journal=fields.get("journal"),
                volume=fields.get("volume"),
                issue=fields.get("number"),
                pages=fields.get("pages"),
                doi=fields.get("doi"),
            ))

        return citations

    def _import_ris(self, content: str) -> list[Citation]:
        """Import from RIS format."""
        try:
            import rispy
            entries = rispy.loads(content)

            citations = []
            for idx, entry in enumerate(entries):
                citation = self._ris_entry_to_citation(entry, idx)
                if citation:
                    citations.append(citation)

            return citations
        except ImportError:
            # Fallback to simple parsing
            return self._simple_ris_parse(content)

    def _ris_entry_to_citation(self, entry: dict, idx: int) -> Citation:
        """Convert RIS entry to Citation."""
        # RIS uses different field names
        authors = entry.get("authors", entry.get("first_authors", []))
        if not isinstance(authors, list):
            authors = [authors] if authors else []

        # Handle pages (SP = start page, EP = end page)
        pages = None
        start_page = entry.get("first_page") or entry.get("start_page")
        end_page = entry.get("last_page") or entry.get("end_page")
        if start_page:
            pages = str(start_page)
            if end_page:
                pages += f"-{end_page}"

        # Get title from various possible fields
        title = (
            entry.get("title") or
            entry.get("primary_title") or
            entry.get("t1")
        )

        # Get journal from various possible fields
        journal = (
            entry.get("journal_name") or
            entry.get("secondary_title") or
            entry.get("j2") or
            entry.get("t2")
        )

        return Citation(
            id=entry.get("id", f"ris_{idx}"),
            raw_text="",
            authors=authors,
            title=title,
            year=_extract_year(entry.get("year") or entry.get("publication_year", "")),
            journal=journal,
            volume=entry.get("volume"),
            issue=entry.get("number"),
            pages=pages,
            doi=entry.get("doi"),
            doi_url=f"https://doi.org/{entry.get('doi')}" if entry.get("doi") else None,
        )

    def _simple_ris_parse(self, content: str) -> list[Citation]:
        """Simple RIS parsing without rispy library."""
        citations = []
        current_entry: dict = {}
        current_authors: list[str] = []

        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Check for tag-value format
            if len(line) >= 6 and line[2:6] == "  - ":
                tag = line[:2]
                value = line[6:].strip()

                if tag == "TY":
                    # Start of new entry
                    if current_entry:
                        current_entry["authors"] = current_authors
                        citations.append(self._dict_to_citation(current_entry, len(citations)))
                    current_entry = {"type": value}
                    current_authors = []
                elif tag == "ER":
                    # End of entry
                    if current_entry:
                        current_entry["authors"] = current_authors
                        citations.append(self._dict_to_citation(current_entry, len(citations)))
                    current_entry = {}
                    current_authors = []
                elif tag == "AU":
                    current_authors.append(value)
                elif tag == "TI" or tag == "T1":
                    current_entry["title"] = value
                elif tag == "PY" or tag == "Y1":
                    current_entry["year"] = value
                elif tag == "JO" or tag == "T2":
                    current_entry["journal"] = value
                elif tag == "VL":
                    current_entry["volume"] = value
                elif tag == "IS":
                    current_entry["issue"] = value
                elif tag == "SP":
                    current_entry["start_page"] = value
                elif tag == "EP":
                    current_entry["end_page"] = value
                elif tag == "DO":
                    current_entry["doi"] = value

        # Handle last entry if no ER tag
        if current_entry:
            current_entry["authors"] = current_authors
            citations.append(self._dict_to_citation(current_entry, len(citations)))

        return citations

    def _dict_to_citation(self, entry: dict, idx: int) -> Citation:
        """Convert parsed dict to Citation."""
        pages = None
        if entry.get("start_page"):
            pages = entry["start_page"]
            if entry.get("end_page"):
                pages += f"-{entry['end_page']}"

        return Citation(
            id=f"ris_{idx}",
            raw_text="",
            authors=entry.get("authors", []),
            title=entry.get("title"),
            year=_extract_year(entry.get("year", "")),
            journal=entry.get("journal"),
            volume=entry.get("volume"),
            issue=entry.get("issue"),
            pages=pages,
            doi=entry.get("doi"),
        )


def _extract_year(date_str: str) -> Optional[int]:
    """Extract year from date string."""
    if not date_str:
        return None
    match = re.search(r'(19|20)\d{2}', str(date_str))
    return int(match.group(0)) if match else None


def compare_with_document(
    imported: list[Citation],
    document_refs: list[Citation],
    title_threshold: int = 85,
) -> ImportResult:
    """
    Compare imported references with document references.

    Args:
        imported: References from reference manager
        document_refs: References parsed from document
        title_threshold: Fuzzy matching threshold for titles

    Returns:
        ImportResult with match statistics
    """
    matched_pairs: list[tuple[Citation, Citation]] = []
    matched_import_ids: set[str] = set()
    matched_doc_ids: set[str] = set()

    # First pass: Match by DOI (exact)
    for imp_ref in imported:
        if not imp_ref.doi:
            continue
        for doc_ref in document_refs:
            if not doc_ref.doi:
                continue
            if imp_ref.doi.lower().strip() == doc_ref.doi.lower().strip():
                matched_pairs.append((imp_ref, doc_ref))
                matched_import_ids.add(imp_ref.id)
                matched_doc_ids.add(doc_ref.id)
                break

    # Second pass: Match by title (fuzzy)
    for imp_ref in imported:
        if imp_ref.id in matched_import_ids:
            continue
        if not imp_ref.title:
            continue

        for doc_ref in document_refs:
            if doc_ref.id in matched_doc_ids:
                continue
            if not doc_ref.title:
                continue

            similarity = fuzz.ratio(
                imp_ref.title.lower(),
                doc_ref.title.lower()
            )
            if similarity >= title_threshold:
                matched_pairs.append((imp_ref, doc_ref))
                matched_import_ids.add(imp_ref.id)
                matched_doc_ids.add(doc_ref.id)
                break

    # Find unmatched references
    unmatched_import = [
        _summarize_citation(ref)
        for ref in imported
        if ref.id not in matched_import_ids
    ]
    unmatched_document = [
        _summarize_citation(ref)
        for ref in document_refs
        if ref.id not in matched_doc_ids
    ]

    # Generate suggestions
    suggestions = []
    if unmatched_document:
        suggestions.append(
            f"{len(unmatched_document)} reference(s) in document not found in your library"
        )
    if unmatched_import:
        suggestions.append(
            f"{len(unmatched_import)} reference(s) in library not cited in document"
        )

    return ImportResult(
        imported_count=len(imported),
        matched_count=len(matched_pairs),
        unmatched_document_refs=unmatched_document,
        unmatched_import_refs=unmatched_import,
        suggestions=suggestions,
    )


def _summarize_citation(ref: Citation) -> str:
    """Create a short summary of a citation for display."""
    parts = []

    if ref.authors:
        first_author = ref.authors[0]
        if "," in first_author:
            first_author = first_author.split(",")[0]
        parts.append(first_author)
        if len(ref.authors) > 1:
            parts.append("et al.")

    if ref.year:
        parts.append(f"({ref.year})")

    if ref.title:
        title = ref.title[:50]
        if len(ref.title) > 50:
            title += "..."
        parts.append(f'"{title}"')

    return " ".join(parts) if parts else ref.id
