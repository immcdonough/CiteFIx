"""Document processing API endpoints."""

import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.models.schemas import (
    Citation,
    CitationStyle,
    ProcessingOptions,
    ProcessingResult,
    ValidationReport,
)
from app.services.citation_detector import detect_citations, parse_references
from app.services.citation_formatter import format_citations_batch
from app.services.docx_parser import parse_docx, update_docx_references
from app.services.doi_resolver import DOIResolver
from app.services.validator import (
    generate_validation_summary,
    validate_citations,
    quick_check_citations,
    QuickCheckResult,
)

router = APIRouter()

# Temporary storage for processed files
TEMP_DIR = Path(tempfile.gettempdir()) / "citefix"
TEMP_DIR.mkdir(exist_ok=True)


@router.post("/quick-check")
async def quick_check_document(file: UploadFile = File(...)):
    """
    Quick check to count matched/unmatched citations without web search.
    Returns time estimate for full validation.
    """
    if not file.filename or not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx files are supported")

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        parsed = parse_docx(tmp_path)
        detection = detect_citations(parsed.body_text)
        references = parse_references(parsed.reference_entries)

        result = quick_check_citations(detection.in_text_citations, references)

        return {
            "total_citations": result.total_citations,
            "total_references": result.total_references,
            "matched": result.matched_count,
            "unmatched": result.unmatched_count,
            "needs_web_search": result.needs_web_search,
            "estimated_time": result.time_estimate_str,
            "estimated_seconds": result.estimated_time_seconds,
        }
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/process", response_model=ProcessingResult)
async def process_document(
    file: UploadFile = File(...),
    style: CitationStyle = Form(CitationStyle.APA),
    example_citations: Optional[str] = Form(None),
    resolve_dois: bool = Form(True),
    validate_citations_opt: bool = Form(True),
    format_citations_opt: bool = Form(True),
    crossref_email: Optional[str] = Form(None),
    enable_web_search: bool = Form(True),
):
    """
    Process a Word document to format citations, resolve DOIs, and validate.

    Args:
        file: The .docx file to process
        style: Citation style to use (APA, MLA, etc.)
        example_citations: Newline-separated example citations for custom formatting
        resolve_dois: Whether to look up DOIs via CrossRef
        validate_citations_opt: Whether to validate citation coverage
        format_citations_opt: Whether to reformat citations
        crossref_email: Email for CrossRef polite pool (faster API access)

    Returns:
        ProcessingResult with validation report and output file info
    """
    # Validate file type
    if not file.filename or not file.filename.endswith(".docx"):
        raise HTTPException(
            status_code=400,
            detail="Only .docx files are supported",
        )

    # Create unique session ID
    session_id = str(uuid.uuid4())
    session_dir = TEMP_DIR / session_id
    session_dir.mkdir(exist_ok=True)

    try:
        # Save uploaded file
        input_path = session_dir / "input.docx"
        with open(input_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Parse document
        parsed = parse_docx(input_path)

        # Detect citations
        detection = detect_citations(parsed.body_text)
        references = parse_references(parsed.reference_entries)

        # Parse example citations if provided
        examples: list[str] = []
        if example_citations:
            examples = [e.strip() for e in example_citations.split("\n") if e.strip()]

        # Resolve DOIs if requested
        dois_resolved = 0
        if resolve_dois and references:
            resolver = DOIResolver(email=crossref_email)
            doi_matches = resolver.resolve_citations_batch(references)

            for ref in references:
                match = doi_matches.get(ref.id)
                if match and not ref.doi:
                    ref.doi = match.doi
                    ref.doi_url = match.doi_url
                    dois_resolved += 1

        # Validate citations if requested
        validation_report: Optional[ValidationReport] = None
        if validate_citations_opt:
            validation_report = validate_citations(
                detection.in_text_citations,
                references,
                detection.detected_type,
                enable_web_search=enable_web_search,
            )

        # Format citations if requested
        output_path = session_dir / "output.docx"
        if format_citations_opt and references:
            if examples:
                formatted_refs = format_citations_batch(
                    references,
                    style=CitationStyle.CUSTOM,
                    examples=examples,
                )
            else:
                formatted_refs = format_citations_batch(
                    references,
                    style=style,
                    examples=None,
                )

            update_docx_references(input_path, output_path, formatted_refs)
        else:
            # Copy original to output
            shutil.copy(input_path, output_path)

        return ProcessingResult(
            success=True,
            message="Document processed successfully",
            validation_report=validation_report,
            citations_found=len(detection.in_text_citations),
            dois_resolved=dois_resolved,
            output_filename=session_id,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing document: {str(e)}",
        )


@router.get("/download/{session_id}")
async def download_processed_document(session_id: str):
    """Download the processed document."""
    output_path = TEMP_DIR / session_id / "output.docx"

    if not output_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Processed document not found. It may have expired.",
        )

    return FileResponse(
        path=output_path,
        filename="citefix_output.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.post("/validate", response_model=ValidationReport)
async def validate_document(file: UploadFile = File(...)):
    """
    Validate citations in a document without modifying it.

    Args:
        file: The .docx file to validate

    Returns:
        ValidationReport with findings
    """
    if not file.filename or not file.filename.endswith(".docx"):
        raise HTTPException(
            status_code=400,
            detail="Only .docx files are supported",
        )

    # Create temp file
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        # Parse and validate
        parsed = parse_docx(tmp_path)
        detection = detect_citations(parsed.body_text)
        references = parse_references(parsed.reference_entries)

        report = validate_citations(
            detection.in_text_citations,
            references,
            detection.detected_type,
        )

        return report

    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("/styles")
async def list_styles():
    """List available citation styles."""
    return {
        "styles": [
            {"id": "apa", "name": "APA (7th Edition)", "description": "American Psychological Association"},
            {"id": "mla", "name": "MLA (9th Edition)", "description": "Modern Language Association"},
            {"id": "chicago-author-date", "name": "Chicago (Author-Date)", "description": "Chicago Manual of Style"},
            {"id": "harvard1", "name": "Harvard", "description": "Harvard referencing style"},
            {"id": "vancouver", "name": "Vancouver", "description": "Medical/scientific style"},
            {"id": "ieee", "name": "IEEE", "description": "Institute of Electrical and Electronics Engineers"},
            {"id": "custom", "name": "Custom", "description": "Learn from example citations"},
        ]
    }
