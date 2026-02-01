#!/usr/bin/env python3
"""Quick debug script to test citation processing."""
import sys
from pathlib import Path

from app.services.docx_parser import parse_docx
from app.services.citation_detector import detect_citations, parse_references
from app.services.validator import validate_citations, _suggest_reference_fix

def debug_document(docx_path: str):
    print(f"=== Parsing: {docx_path} ===\n")
    
    # Parse document
    parsed = parse_docx(docx_path)
    print(f"Found {len(parsed.reference_entries)} reference entries\n")
    
    # Show first few references and their parsed data
    print("=== PARSED REFERENCES ===")
    references = parse_references(parsed.reference_entries)
    for i, ref in enumerate(references[:10]):  # First 10
        print(f"\n[{i+1}] Raw: {ref.raw_text[:70]}...")
        print(f"    Authors: {ref.authors}")
        print(f"    Year: {ref.year}")
    
    # Detect citations
    print("\n\n=== IN-TEXT CITATIONS ===")
    detection = detect_citations(parsed.body_text)
    for cit in detection.in_text_citations[:10]:  # First 10
        print(f"  {cit.text}")
        print(f"    Context: ...{cit.context[:60]}...")
    
    # Validate
    print("\n\n=== VALIDATION ===")
    report = validate_citations(detection.in_text_citations, references, detection.detected_type)
    print(f"Matched: {report.matched_citations}/{report.total_in_text_citations}")
    print(f"Issues: {len(report.issues)}")
    
    # Show first few issues with suggestions
    for issue in report.issues[:5]:
        if issue.issue_type == "missing_reference":
            print(f"\n  MISSING: {issue.citation_text}")
            print(f"  SUGGESTION: {issue.suggestion}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3.11 debug_test.py <path_to_docx>")
        sys.exit(1)
    debug_document(sys.argv[1])
