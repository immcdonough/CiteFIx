"""Tests for bibliography exporter."""

import pytest

from app.models.schemas import Citation, BibFormat
from app.services.bibliography_exporter import (
    export_references,
    export_to_file,
)


class TestBibTeXExport:
    """Tests for BibTeX export."""

    def test_basic_article(self):
        """Test exporting a basic article to BibTeX."""
        refs = [
            Citation(
                id="smith2020",
                raw_text="Smith, J. (2020). Title. Journal, 10(2), 45-67.",
                authors=["Smith, J."],
                title="Test Article Title",
                year=2020,
                journal="Test Journal",
                volume="10",
                issue="2",
                pages="45-67",
            )
        ]

        result = export_references(refs, BibFormat.BIBTEX)

        assert result.format == BibFormat.BIBTEX
        assert result.entry_count == 1
        assert "@article{" in result.content
        assert "author = {Smith, J.}" in result.content
        assert "title = {{Test Article Title}}" in result.content
        assert "year = {2020}" in result.content
        assert "journal = {Test Journal}" in result.content
        assert "volume = {10}" in result.content
        assert "number = {2}" in result.content
        assert "pages = {45--67}" in result.content

    def test_with_doi(self):
        """Test exporting reference with DOI."""
        refs = [
            Citation(
                id="jones2019",
                raw_text="Jones, B. (2019). Title. Journal.",
                authors=["Jones, B."],
                title="Title with DOI",
                year=2019,
                doi="10.1234/example.doi",
            )
        ]

        result = export_references(refs, BibFormat.BIBTEX)

        assert "doi = {10.1234/example.doi}" in result.content

    def test_multiple_authors(self):
        """Test exporting reference with multiple authors."""
        refs = [
            Citation(
                id="multi2020",
                raw_text="Smith, J., Jones, B., Brown, C. (2020). Title.",
                authors=["Smith, J.", "Jones, B.", "Brown, C."],
                title="Multi-Author Paper",
                year=2020,
            )
        ]

        result = export_references(refs, BibFormat.BIBTEX)

        # Authors should be joined with " and "
        assert "author = {Smith, J. and Jones, B. and Brown, C.}" in result.content

    def test_special_characters(self):
        """Test escaping special LaTeX characters."""
        refs = [
            Citation(
                id="special2020",
                raw_text="Test",
                authors=["O'Connor, J."],
                title="Test & Compare: 100% Results",
                year=2020,
            )
        ]

        result = export_references(refs, BibFormat.BIBTEX)

        # & should be escaped
        assert r"\&" in result.content or "\\&" in result.content
        # % should be escaped
        assert r"\%" in result.content or "\\%" in result.content

    def test_unique_citation_keys(self):
        """Test that duplicate authors/years get unique keys."""
        refs = [
            Citation(
                id="ref1",
                raw_text="Smith, J. (2020). First paper.",
                authors=["Smith, J."],
                title="First paper",
                year=2020,
            ),
            Citation(
                id="ref2",
                raw_text="Smith, J. (2020). Second paper.",
                authors=["Smith, J."],
                title="Second paper",
                year=2020,
            ),
        ]

        result = export_references(refs, BibFormat.BIBTEX)

        # Should have smith2020 and smith2020a (or similar unique keys)
        assert "smith2020" in result.content.lower()
        # Check for some differentiator
        lines = result.content.split("\n")
        article_lines = [l for l in lines if "@article{" in l.lower()]
        keys = [l.split("{")[1].rstrip(",") for l in article_lines]
        assert len(keys) == len(set(keys))  # All unique

    def test_missing_fields_warning(self):
        """Test that warnings are generated for missing required fields."""
        refs = [
            Citation(
                id="incomplete",
                raw_text="Incomplete reference",
                authors=[],  # Missing authors
                # Missing title and year
            )
        ]

        result = export_references(refs, BibFormat.BIBTEX)

        assert len(result.warnings) > 0
        assert any("authors" in w.lower() for w in result.warnings)


class TestRISExport:
    """Tests for RIS export."""

    def test_basic_article(self):
        """Test exporting a basic article to RIS."""
        refs = [
            Citation(
                id="test1",
                raw_text="Smith, J. (2020). Title. Journal.",
                authors=["Smith, J."],
                title="Test Article",
                year=2020,
                journal="Test Journal",
                volume="10",
                issue="2",
                pages="45-67",
            )
        ]

        result = export_references(refs, BibFormat.RIS)

        assert result.format == BibFormat.RIS
        assert result.entry_count == 1
        assert "TY  - JOUR" in result.content
        assert "AU  - Smith, J." in result.content
        assert "TI  - Test Article" in result.content
        assert "PY  - 2020" in result.content
        assert "JO  - Test Journal" in result.content
        assert "VL  - 10" in result.content
        assert "IS  - 2" in result.content
        assert "SP  - 45" in result.content
        assert "EP  - 67" in result.content
        assert "ER  - " in result.content

    def test_with_doi_and_url(self):
        """Test exporting reference with DOI and URL."""
        refs = [
            Citation(
                id="test2",
                raw_text="Jones, B. (2019). Title.",
                authors=["Jones, B."],
                title="Title",
                year=2019,
                doi="10.1234/test",
                doi_url="https://doi.org/10.1234/test",
            )
        ]

        result = export_references(refs, BibFormat.RIS)

        assert "DO  - 10.1234/test" in result.content
        assert "UR  - https://doi.org/10.1234/test" in result.content

    def test_multiple_authors(self):
        """Test exporting multiple authors in RIS format."""
        refs = [
            Citation(
                id="multi",
                raw_text="Smith, J., Jones, B. (2020). Title.",
                authors=["Smith, J.", "Jones, B."],
                title="Title",
                year=2020,
            )
        ]

        result = export_references(refs, BibFormat.RIS)

        # Each author should be on separate AU line
        assert result.content.count("AU  - ") == 2

    def test_page_range_parsing(self):
        """Test proper parsing of page ranges."""
        refs = [
            Citation(
                id="pages",
                raw_text="Test",
                authors=["Test, A."],
                title="Title",
                year=2020,
                pages="100-150",
            )
        ]

        result = export_references(refs, BibFormat.RIS)

        assert "SP  - 100" in result.content
        assert "EP  - 150" in result.content


class TestExportToFile:
    """Tests for file export."""

    def test_export_to_bibtex_file(self, tmp_path):
        """Test exporting to a BibTeX file."""
        refs = [
            Citation(
                id="test",
                raw_text="Smith, J. (2020). Title.",
                authors=["Smith, J."],
                title="Title",
                year=2020,
            )
        ]

        output_file = tmp_path / "output.bib"
        result = export_to_file(refs, str(output_file), BibFormat.BIBTEX)

        assert output_file.exists()
        content = output_file.read_text()
        assert "@article{" in content

    def test_export_to_ris_file(self, tmp_path):
        """Test exporting to a RIS file."""
        refs = [
            Citation(
                id="test",
                raw_text="Smith, J. (2020). Title.",
                authors=["Smith, J."],
                title="Title",
                year=2020,
            )
        ]

        output_file = tmp_path / "output.ris"
        result = export_to_file(refs, str(output_file), BibFormat.RIS)

        assert output_file.exists()
        content = output_file.read_text()
        assert "TY  - JOUR" in content


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_list(self):
        """Test exporting empty reference list."""
        result = export_references([], BibFormat.BIBTEX)

        assert result.entry_count == 0
        assert result.content == ""

    def test_unicode_characters(self):
        """Test handling of unicode characters."""
        refs = [
            Citation(
                id="unicode",
                raw_text="M\u00fcller, J. (2020). Caf\u00e9 studies.",
                authors=["M\u00fcller, J."],
                title="Caf\u00e9 studies in Z\u00fcrich",
                year=2020,
            )
        ]

        result = export_references(refs, BibFormat.BIBTEX)

        # Should not crash
        assert result.entry_count == 1
