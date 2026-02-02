"""Retraction checking service using CrossRef API."""

from dataclasses import dataclass
from typing import Optional

import httpx

from app.models.schemas import Citation, ValidationIssue, IssueSeverity


CROSSREF_API = "https://api.crossref.org/works"


@dataclass
class RetractionStatus:
    """Status of retraction check for a reference."""
    reference_id: str
    doi: str
    is_retracted: bool
    retraction_date: Optional[str] = None
    retraction_reason: Optional[str] = None
    retraction_notice_doi: Optional[str] = None
    error: Optional[str] = None


class RetractionChecker:
    """Check for retracted papers using CrossRef API."""

    def __init__(self, email: Optional[str] = None, timeout: float = 10.0):
        """
        Initialize the retraction checker.

        Args:
            email: Email for CrossRef polite pool (faster rate limits)
            timeout: Request timeout in seconds
        """
        self.email = email
        self.timeout = timeout
        self._cache: dict[str, RetractionStatus] = {}

    def check_reference(self, ref: Citation) -> Optional[RetractionStatus]:
        """
        Check if a single reference has been retracted.

        Args:
            ref: Citation to check

        Returns:
            RetractionStatus or None if no DOI
        """
        if not ref.doi:
            return None

        # Check cache
        normalized_doi = ref.doi.lower().strip()
        if normalized_doi in self._cache:
            return self._cache[normalized_doi]

        status = self._query_crossref(ref.doi, ref.id)
        self._cache[normalized_doi] = status
        return status

    def check_references(
        self,
        references: list[Citation],
        progress_callback: Optional[callable] = None,
    ) -> list[ValidationIssue]:
        """
        Check all references for retractions.

        Args:
            references: List of Citation objects
            progress_callback: Optional callback for progress updates

        Returns:
            List of ValidationIssue for retracted papers
        """
        issues = []
        refs_with_doi = [r for r in references if r.doi]
        total = len(refs_with_doi)

        for idx, ref in enumerate(refs_with_doi):
            if progress_callback:
                progress_callback(idx + 1, total, f"Checking {ref.id}")

            status = self.check_reference(ref)

            if status and status.is_retracted:
                # Build suggestion with available info
                suggestion_parts = ["This paper has been retracted."]

                if status.retraction_date:
                    suggestion_parts.append(f"Retraction date: {status.retraction_date}")

                if status.retraction_notice_doi:
                    suggestion_parts.append(
                        f"See retraction notice: https://doi.org/{status.retraction_notice_doi}"
                    )
                else:
                    suggestion_parts.append(
                        f"See: https://doi.org/{ref.doi}"
                    )

                suggestion_parts.append("Consider removing or noting the retraction status.")

                issues.append(ValidationIssue(
                    issue_type="retracted_reference",
                    description="RETRACTED PAPER: This reference has been retracted",
                    citation_text=_truncate(ref.raw_text, 100) if ref.raw_text else ref.id,
                    suggestion=" ".join(suggestion_parts),
                    severity=IssueSeverity.ERROR,  # High severity
                ))

        return issues

    def _query_crossref(self, doi: str, ref_id: str) -> RetractionStatus:
        """Query CrossRef API for retraction status."""
        try:
            headers = {
                "Accept": "application/json",
            }
            if self.email:
                headers["User-Agent"] = f"CiteFix/1.0 (mailto:{self.email})"

            # Clean DOI
            doi = doi.strip()
            if doi.startswith("https://doi.org/"):
                doi = doi[len("https://doi.org/"):]
            elif doi.startswith("http://doi.org/"):
                doi = doi[len("http://doi.org/"):]

            url = f"{CROSSREF_API}/{doi}"

            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, headers=headers)

                if response.status_code == 404:
                    return RetractionStatus(
                        reference_id=ref_id,
                        doi=doi,
                        is_retracted=False,
                        error="DOI not found in CrossRef",
                    )

                if response.status_code != 200:
                    return RetractionStatus(
                        reference_id=ref_id,
                        doi=doi,
                        is_retracted=False,
                        error=f"API returned {response.status_code}",
                    )

                data = response.json()
                message = data.get("message", {})

                # Check for retraction markers

                # Method 1: Check "update-to" field
                updates = message.get("update-to", [])
                for update in updates:
                    update_type = update.get("type", "").lower()
                    if "retract" in update_type:
                        return RetractionStatus(
                            reference_id=ref_id,
                            doi=doi,
                            is_retracted=True,
                            retraction_notice_doi=update.get("DOI"),
                            retraction_date=_extract_date(update.get("updated")),
                        )

                # Method 2: Check "relation" field
                relations = message.get("relation", {})

                # Check if this paper is retracted by something
                if "is-retracted-by" in relations:
                    retracted_by = relations["is-retracted-by"]
                    notice_doi = None
                    if isinstance(retracted_by, list) and retracted_by:
                        notice_doi = retracted_by[0].get("id")
                    return RetractionStatus(
                        reference_id=ref_id,
                        doi=doi,
                        is_retracted=True,
                        retraction_notice_doi=notice_doi,
                    )

                # Method 3: Check "type" field
                item_type = message.get("type", "").lower()
                if item_type == "retraction":
                    return RetractionStatus(
                        reference_id=ref_id,
                        doi=doi,
                        is_retracted=True,
                    )

                # Method 4: Check title for retraction keywords
                title = message.get("title", [""])[0].lower() if message.get("title") else ""
                if any(word in title for word in ["retracted:", "retraction:", "[retracted]"]):
                    return RetractionStatus(
                        reference_id=ref_id,
                        doi=doi,
                        is_retracted=True,
                    )

                return RetractionStatus(
                    reference_id=ref_id,
                    doi=doi,
                    is_retracted=False,
                )

        except httpx.TimeoutException:
            return RetractionStatus(
                reference_id=ref_id,
                doi=doi,
                is_retracted=False,
                error="Request timed out",
            )
        except Exception as e:
            return RetractionStatus(
                reference_id=ref_id,
                doi=doi,
                is_retracted=False,
                error=str(e),
            )

    def get_retraction_stats(
        self,
        references: list[Citation],
    ) -> dict:
        """
        Get statistics about retraction checking.

        Returns:
            Dict with counts and lists
        """
        refs_with_doi = [r for r in references if r.doi]
        refs_without_doi = [r for r in references if not r.doi]

        retracted = []
        not_retracted = []
        errors = []

        for ref in refs_with_doi:
            status = self.check_reference(ref)
            if status:
                if status.is_retracted:
                    retracted.append(ref.id)
                elif status.error:
                    errors.append((ref.id, status.error))
                else:
                    not_retracted.append(ref.id)

        return {
            "total_references": len(references),
            "with_doi": len(refs_with_doi),
            "without_doi": len(refs_without_doi),
            "retracted_count": len(retracted),
            "retracted_ids": retracted,
            "checked_ok": len(not_retracted),
            "errors": errors,
        }


def _extract_date(date_parts: Optional[dict]) -> Optional[str]:
    """Extract date string from CrossRef date-parts format."""
    if not date_parts:
        return None

    parts = date_parts.get("date-parts", [[]])
    if parts and parts[0]:
        date_list = parts[0]
        if len(date_list) >= 1:
            year = date_list[0]
            if len(date_list) >= 2:
                month = date_list[1]
                if len(date_list) >= 3:
                    day = date_list[2]
                    return f"{year}-{month:02d}-{day:02d}"
                return f"{year}-{month:02d}"
            return str(year)

    return None


def _truncate(text: str, max_length: int) -> str:
    """Truncate text to max_length, adding ellipsis if needed."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."
