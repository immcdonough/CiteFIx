"""DOI resolution service using CrossRef API."""

import asyncio
import re
from dataclasses import dataclass
from typing import Optional

import httpx
from habanero import Crossref

from app.models.schemas import Citation


@dataclass
class DOIMatch:
    """Result of a DOI lookup."""
    doi: str
    doi_url: str
    title: str
    authors: list[str]
    year: Optional[int]
    confidence: float  # 0.0 to 1.0


class DOIResolver:
    """Service for resolving DOIs via CrossRef API."""

    def __init__(self, email: Optional[str] = None):
        """
        Initialize the DOI resolver.

        Args:
            email: Optional email for polite pool access (faster rate limits)
        """
        self.cr = Crossref(mailto=email) if email else Crossref()
        self._cache: dict[str, Optional[DOIMatch]] = {}

    def resolve_citation(self, citation: Citation) -> Optional[DOIMatch]:
        """
        Look up DOI for a citation.

        Args:
            citation: Citation to resolve

        Returns:
            DOIMatch if found, None otherwise
        """
        # Check cache first
        cache_key = self._make_cache_key(citation)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # If citation already has DOI, verify it
        if citation.doi:
            match = self._verify_doi(citation.doi)
            self._cache[cache_key] = match
            return match

        # Search by title and author
        match = self._search_crossref(citation)
        self._cache[cache_key] = match
        return match

    def resolve_citations_batch(
        self,
        citations: list[Citation],
        max_concurrent: int = 5,
    ) -> dict[str, Optional[DOIMatch]]:
        """
        Resolve DOIs for multiple citations.

        Args:
            citations: List of citations to resolve
            max_concurrent: Max concurrent API requests

        Returns:
            Dict mapping citation IDs to DOIMatch results
        """
        results: dict[str, Optional[DOIMatch]] = {}

        for citation in citations:
            try:
                match = self.resolve_citation(citation)
                results[citation.id] = match
            except Exception as e:
                # Log error but continue with other citations
                print(f"Error resolving DOI for {citation.id}: {e}")
                results[citation.id] = None

        return results

    def _search_crossref(self, citation: Citation) -> Optional[DOIMatch]:
        """Search CrossRef for a matching work."""
        query_parts: list[str] = []

        if citation.title:
            query_parts.append(citation.title)

        if citation.authors:
            # Add first author's last name
            first_author = citation.authors[0]
            if "," in first_author:
                last_name = first_author.split(",")[0]
            else:
                last_name = first_author.split()[-1] if first_author.split() else first_author
            query_parts.append(last_name)

        if not query_parts:
            return None

        query = " ".join(query_parts)

        try:
            # Search CrossRef
            results = self.cr.works(
                query=query,
                limit=5,
                select="DOI,title,author,published-print,published-online,score",
            )

            if not results or "message" not in results:
                return None

            items = results["message"].get("items", [])
            if not items:
                return None

            # Find best match
            best_match = self._find_best_match(citation, items)
            return best_match

        except Exception as e:
            print(f"CrossRef search error: {e}")
            return None

    def _verify_doi(self, doi: str) -> Optional[DOIMatch]:
        """Verify a DOI exists and get metadata."""
        try:
            result = self.cr.works(ids=doi)
            if not result or "message" not in result:
                return None

            item = result["message"]
            return self._item_to_match(item, confidence=1.0)

        except Exception:
            return None

    def _find_best_match(
        self,
        citation: Citation,
        items: list[dict],
    ) -> Optional[DOIMatch]:
        """Find the best matching item from search results."""
        best_match: Optional[DOIMatch] = None
        best_score = 0.0

        for item in items:
            score = self._calculate_match_score(citation, item)
            if score > best_score and score >= 0.5:  # Minimum threshold
                best_score = score
                best_match = self._item_to_match(item, confidence=score)

        return best_match

    def _calculate_match_score(self, citation: Citation, item: dict) -> float:
        """Calculate how well an item matches the citation."""
        score = 0.0
        weights_used = 0.0

        # Title similarity (weight: 0.5)
        if citation.title and "title" in item:
            item_title = item["title"][0] if isinstance(item["title"], list) else item["title"]
            title_sim = self._string_similarity(citation.title, item_title)
            score += title_sim * 0.5
            weights_used += 0.5

        # Author match (weight: 0.3)
        if citation.authors and "author" in item:
            author_score = self._author_match_score(citation.authors, item["author"])
            score += author_score * 0.3
            weights_used += 0.3

        # Year match (weight: 0.2)
        if citation.year:
            item_year = self._extract_year(item)
            if item_year:
                if item_year == citation.year:
                    score += 0.2
                elif abs(item_year - citation.year) <= 1:
                    score += 0.1
                weights_used += 0.2

        # Normalize score
        if weights_used > 0:
            score = score / weights_used

        return score

    def _string_similarity(self, s1: str, s2: str) -> float:
        """Calculate simple string similarity."""
        s1 = s1.lower().strip()
        s2 = s2.lower().strip()

        if s1 == s2:
            return 1.0

        # Word overlap
        words1 = set(re.findall(r'\w+', s1))
        words2 = set(re.findall(r'\w+', s2))

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    def _author_match_score(
        self,
        citation_authors: list[str],
        item_authors: list[dict],
    ) -> float:
        """Calculate author match score."""
        if not citation_authors or not item_authors:
            return 0.0

        # Extract last names from citation
        citation_last_names = []
        for author in citation_authors:
            if "," in author:
                last = author.split(",")[0].strip().lower()
            else:
                parts = author.split()
                last = parts[-1].lower() if parts else author.lower()
            citation_last_names.append(last)

        # Extract last names from item
        item_last_names = []
        for author in item_authors:
            if "family" in author:
                item_last_names.append(author["family"].lower())

        if not item_last_names:
            return 0.0

        # Check overlap
        matches = sum(1 for name in citation_last_names if name in item_last_names)
        return matches / max(len(citation_last_names), len(item_last_names))

    def _extract_year(self, item: dict) -> Optional[int]:
        """Extract publication year from CrossRef item."""
        for field in ["published-print", "published-online", "issued"]:
            if field in item and "date-parts" in item[field]:
                parts = item[field]["date-parts"]
                if parts and parts[0] and len(parts[0]) > 0:
                    return parts[0][0]
        return None

    def _item_to_match(self, item: dict, confidence: float) -> DOIMatch:
        """Convert CrossRef item to DOIMatch."""
        doi = item.get("DOI", "")

        # Get title
        title = ""
        if "title" in item:
            title = item["title"][0] if isinstance(item["title"], list) else item["title"]

        # Get authors
        authors: list[str] = []
        if "author" in item:
            for author in item["author"]:
                name_parts = []
                if "given" in author:
                    name_parts.append(author["given"])
                if "family" in author:
                    name_parts.append(author["family"])
                if name_parts:
                    authors.append(" ".join(name_parts))

        # Get year
        year = self._extract_year(item)

        return DOIMatch(
            doi=doi,
            doi_url=f"https://doi.org/{doi}",
            title=title,
            authors=authors,
            year=year,
            confidence=confidence,
        )

    def _make_cache_key(self, citation: Citation) -> str:
        """Create cache key for citation."""
        parts = [
            citation.title or "",
            ",".join(citation.authors[:2]) if citation.authors else "",
            str(citation.year or ""),
        ]
        return "|".join(parts).lower()


# Convenience function for simple usage
def resolve_doi(citation: Citation, email: Optional[str] = None) -> Optional[DOIMatch]:
    """
    Resolve DOI for a single citation.

    Args:
        citation: Citation to resolve
        email: Optional email for CrossRef polite pool

    Returns:
        DOIMatch if found, None otherwise
    """
    resolver = DOIResolver(email=email)
    return resolver.resolve_citation(citation)


def resolve_dois_batch(
    citations: list[Citation],
    email: Optional[str] = None,
) -> dict[str, Optional[DOIMatch]]:
    """
    Resolve DOIs for multiple citations.

    Args:
        citations: List of citations to resolve
        email: Optional email for CrossRef polite pool

    Returns:
        Dict mapping citation IDs to DOIMatch results
    """
    resolver = DOIResolver(email=email)
    return resolver.resolve_citations_batch(citations)
