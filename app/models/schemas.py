"""Pydantic models for CiteFix."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CitationStyle(str, Enum):
    """Supported citation styles."""
    APA = "apa"
    MLA = "mla"
    CHICAGO = "chicago-author-date"
    HARVARD = "harvard1"
    VANCOUVER = "vancouver"
    IEEE = "ieee"
    CUSTOM = "custom"


class CitationType(str, Enum):
    """Types of in-text citation formats."""
    AUTHOR_YEAR = "author_year"      # (Smith, 2020)
    NUMERIC = "numeric"               # [1] or superscript
    AUTHOR_YEAR_INLINE = "author_inline"  # Smith (2020)


class Citation(BaseModel):
    """Represents a single citation reference."""
    id: str = Field(..., description="Unique identifier for this citation")
    raw_text: str = Field(..., description="Original citation text as found")
    authors: list[str] = Field(default_factory=list)
    title: Optional[str] = None
    year: Optional[int] = None
    journal: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None
    doi_url: Optional[str] = None
    confidence: float = Field(default=0.0, description="Confidence score 0-1")


class InTextCitation(BaseModel):
    """Represents an in-text citation occurrence."""
    text: str = Field(..., description="The citation text as it appears")
    start_pos: int = Field(..., description="Start position in document")
    end_pos: int = Field(..., description="End position in document")
    citation_type: CitationType
    reference_ids: list[str] = Field(default_factory=list, description="Matched reference IDs")
    context: str = Field(default="", description="Surrounding text for context-aware matching")


class ValidationIssue(BaseModel):
    """A validation issue found in the document."""
    issue_type: str = Field(..., description="Type: missing_reference, uncited, duplicate")
    description: str
    citation_text: Optional[str] = None
    suggestion: Optional[str] = None


class ValidationReport(BaseModel):
    """Complete validation report for a document."""
    total_in_text_citations: int
    total_references: int
    matched_citations: int
    issues: list[ValidationIssue] = Field(default_factory=list)
    is_valid: bool = Field(default=False)


class ProcessingOptions(BaseModel):
    """Options for document processing."""
    style: CitationStyle = CitationStyle.APA
    example_citations: list[str] = Field(default_factory=list, description="Example formatted citations")
    resolve_dois: bool = Field(default=True, description="Look up DOIs via CrossRef")
    validate_citations: bool = Field(default=True, description="Check citation coverage")
    format_citations: bool = Field(default=True, description="Reformat citations")


class ProcessingResult(BaseModel):
    """Result of document processing."""
    success: bool
    message: str
    validation_report: Optional[ValidationReport] = None
    citations_found: int = 0
    dois_resolved: int = 0
    output_filename: Optional[str] = None
