"""Tests for reference importer."""

import pytest

from app.models.schemas import Citation, ReferenceManagerType
from app.services.reference_importer import (
    ReferenceImporter,
    compare_with_document,
)


class TestZoteroImport:
    """Tests for Zotero JSON import."""

    def test_basic_import(self):
        """Test importing basic Zotero JSON."""
        json_content = """[
            {
                "key": "ABC123",
                "title": "Test Article",
                "creators": [
                    {"creatorType": "author", "lastName": "Smith", "firstName": "John"}
                ],
                "date": "2020",
                "publicationTitle": "Test Journal",
                "volume": "10",
                "issue": "2",
                "pages": "45-67",
                "DOI": "10.1234/test"
            }
        ]"""

        importer = ReferenceImporter()
        refs = importer.import_content(json_content, ReferenceManagerType.ZOTERO)

        assert len(refs) == 1
        assert refs[0].title == "Test Article"
        assert refs[0].authors == ["Smith, John"]
        assert refs[0].year == 2020
        assert refs[0].journal == "Test Journal"
        assert refs[0].doi == "10.1234/test"

    def test_multiple_authors(self):
        """Test importing reference with multiple authors."""
        json_content = """[
            {
                "key": "XYZ789",
                "title": "Multi-Author Paper",
                "creators": [
                    {"creatorType": "author", "lastName": "Smith", "firstName": "J."},
                    {"creatorType": "author", "lastName": "Jones", "firstName": "B."},
                    {"creatorType": "editor", "lastName": "Brown", "firstName": "C."}
                ],
                "date": "2019"
            }
        ]"""

        importer = ReferenceImporter()
        refs = importer.import_content(json_content, ReferenceManagerType.ZOTERO)

        assert len(refs) == 1
        # Should only include authors, not editors
        assert len(refs[0].authors) == 2
        assert "Smith, J." in refs[0].authors
        assert "Jones, B." in refs[0].authors

    def test_doi_in_extra_field(self):
        """Test extracting DOI from Zotero's extra field."""
        json_content = """[
            {
                "key": "DOI123",
                "title": "Paper with DOI in Extra",
                "creators": [{"creatorType": "author", "lastName": "Test"}],
                "date": "2020",
                "extra": "DOI: 10.1234/extra.doi\\nOther info"
            }
        ]"""

        importer = ReferenceImporter()
        refs = importer.import_content(json_content, ReferenceManagerType.ZOTERO)

        assert refs[0].doi == "10.1234/extra.doi"


class TestBibTeXImport:
    """Tests for BibTeX import (Mendeley format)."""

    def test_basic_bibtex(self):
        """Test importing basic BibTeX."""
        bibtex_content = """@article{smith2020,
            author = {Smith, John and Jones, Bob},
            title = {Test Article Title},
            journal = {Test Journal},
            year = {2020},
            volume = {10},
            number = {2},
            pages = {45-67},
            doi = {10.1234/test}
        }"""

        importer = ReferenceImporter()
        refs = importer.import_content(bibtex_content, ReferenceManagerType.MENDELEY)

        assert len(refs) == 1
        assert refs[0].id == "smith2020"
        assert "Smith, John" in refs[0].authors
        assert "Jones, Bob" in refs[0].authors
        assert refs[0].title == "Test Article Title"
        assert refs[0].year == 2020

    def test_braces_removed_from_title(self):
        """Test that braces are removed from BibTeX titles."""
        bibtex_content = """@article{test,
            author = {Test},
            title = {{Protected {Title} with Braces}},
            year = {2020}
        }"""

        importer = ReferenceImporter()
        refs = importer.import_content(bibtex_content, ReferenceManagerType.MENDELEY)

        assert "{" not in refs[0].title
        assert "}" not in refs[0].title


class TestRISImport:
    """Tests for RIS import (EndNote format)."""

    def test_basic_ris(self):
        """Test importing basic RIS format."""
        ris_content = """TY  - JOUR
AU  - Smith, John
AU  - Jones, Bob
TI  - Test Article Title
JO  - Test Journal
PY  - 2020
VL  - 10
IS  - 2
SP  - 45
EP  - 67
DO  - 10.1234/test
ER  -
"""

        importer = ReferenceImporter()
        refs = importer.import_content(ris_content, ReferenceManagerType.ENDNOTE)

        assert len(refs) == 1
        assert refs[0].title == "Test Article Title"
        assert "Smith, John" in refs[0].authors
        assert "Jones, Bob" in refs[0].authors
        assert refs[0].year == 2020
        assert refs[0].pages == "45-67"
        assert refs[0].doi == "10.1234/test"

    def test_multiple_entries(self):
        """Test importing multiple RIS entries."""
        ris_content = """TY  - JOUR
AU  - Smith, John
TI  - First Paper
PY  - 2020
ER  -

TY  - JOUR
AU  - Jones, Bob
TI  - Second Paper
PY  - 2019
ER  -
"""

        importer = ReferenceImporter()
        refs = importer.import_content(ris_content, ReferenceManagerType.ENDNOTE)

        assert len(refs) == 2


class TestDocumentComparison:
    """Tests for comparing imported references with document."""

    def test_doi_match(self):
        """Test matching by DOI."""
        imported = [
            Citation(
                id="imp1",
                raw_text="",
                title="Paper A",
                doi="10.1234/test",
            )
        ]
        document = [
            Citation(
                id="doc1",
                raw_text="Smith (2020). Paper A.",
                title="Paper A",
                doi="10.1234/test",
            )
        ]

        result = compare_with_document(imported, document)

        assert result.imported_count == 1
        assert result.matched_count == 1
        assert len(result.unmatched_document_refs) == 0
        assert len(result.unmatched_import_refs) == 0

    def test_title_fuzzy_match(self):
        """Test fuzzy matching by title."""
        imported = [
            Citation(
                id="imp1",
                raw_text="",
                title="Brain Activity During Sleep: A Study",
                authors=["Smith, J."],
                year=2020,
            )
        ]
        document = [
            Citation(
                id="doc1",
                raw_text="Smith (2020).",
                title="Brain activity during sleep: a study",  # Same but lowercase
                authors=["Smith, J."],
                year=2020,
            )
        ]

        result = compare_with_document(imported, document)

        assert result.matched_count == 1

    def test_unmatched_references(self):
        """Test detecting unmatched references."""
        imported = [
            Citation(
                id="imp1",
                raw_text="",
                title="Paper in Library Only",
                authors=["Smith, J."],
                year=2020,
            )
        ]
        document = [
            Citation(
                id="doc1",
                raw_text="Jones (2019). Paper in Document Only.",
                title="Paper in Document Only",
                authors=["Jones, B."],
                year=2019,
            )
        ]

        result = compare_with_document(imported, document)

        assert result.matched_count == 0
        assert len(result.unmatched_import_refs) == 1
        assert len(result.unmatched_document_refs) == 1

    def test_suggestions_generated(self):
        """Test that suggestions are generated."""
        imported = [
            Citation(
                id="imp1",
                raw_text="",
                title="Extra Paper",
                authors=["Extra"],
            )
        ]
        document = [
            Citation(
                id="doc1",
                raw_text="Missing (2020).",
                title="Missing Paper",
                authors=["Missing"],
            )
        ]

        result = compare_with_document(imported, document)

        assert len(result.suggestions) > 0


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_import(self):
        """Test importing empty content."""
        importer = ReferenceImporter()

        # Empty JSON array
        refs = importer.import_content("[]", ReferenceManagerType.ZOTERO)
        assert len(refs) == 0

    def test_unsupported_format(self):
        """Test handling of unsupported format."""
        importer = ReferenceImporter()

        with pytest.raises(ValueError):
            importer.import_content("content", ReferenceManagerType("unsupported"))

    def test_malformed_json(self):
        """Test handling of malformed JSON."""
        importer = ReferenceImporter()

        with pytest.raises(Exception):
            importer.import_content("{invalid json", ReferenceManagerType.ZOTERO)
