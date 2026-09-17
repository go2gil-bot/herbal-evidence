"""PubMed E-utilities adapter.

https://www.ncbi.nlm.nih.gov/books/NBK25497/

NCBI asks callers to identify themselves with `tool` and `email`, and to stay
under 3 requests per second without an API key (10 with one). Both the key and
the contact address come from configuration - no address is hardcoded, because
sending someone's email to a third party is their decision, not the code's.

esummary gives metadata without the full record, which is all that is needed to
create a source row; the abstract comes from Europe PMC, which returns it in the
same search response.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.research import classify
from app.research.http import get
from app.research.models import RetrievedSource

logger = logging.getLogger("herbal_evidence.research.pubmed")

PROVIDER = "pubmed"
BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "HerbalEvidence"

# Without an API key NCBI allows 3 requests/second. Two sequential calls per
# search is well inside that, and the sleep keeps a retry storm from crossing it.
POLITE_DELAY_SECONDS = 0.35


def _identity() -> dict[str, str]:
    settings = get_settings()
    params = {"tool": TOOL}
    if settings.ncbi_api_key:
        params["api_key"] = settings.ncbi_api_key
    if settings.ncbi_contact_email:
        params["email"] = settings.ncbi_contact_email
    return params


async def _esearch(query: str, limit: int) -> list[str]:
    response = await get(
        f"{BASE}/esearch.fcgi",
        params={
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": str(min(limit, 100)),
            **_identity(),
        },
    )
    payload = response.json()
    return (payload.get("esearchresult") or {}).get("idlist") or []


async def _esummary(pmids: list[str]) -> list[dict]:
    if not pmids:
        return []
    response = await get(
        f"{BASE}/esummary.fcgi",
        params={"db": "pubmed", "id": ",".join(pmids), "retmode": "json", **_identity()},
    )
    payload = response.json().get("result") or {}
    return [payload[pmid] for pmid in payload.get("uids", []) if pmid in payload]


def _parse(summary: dict) -> RetrievedSource:
    pub_types = summary.get("pubtype") or []

    doi = None
    for article_id in summary.get("articleids") or []:
        if article_id.get("idtype") == "doi":
            doi = article_id.get("value")
            break

    year = None
    pubdate = summary.get("pubdate") or ""
    if pubdate[:4].isdigit():
        year = int(pubdate[:4])

    return RetrievedSource(
        provider=PROVIDER,
        title=(summary.get("title") or "").strip().rstrip("."),
        pmid=summary.get("uid"),
        doi=doi,
        journal=summary.get("fulljournalname") or summary.get("source"),
        publication_year=year,
        # esummary carries no MeSH headings, so labelling from it alone would be
        # a guess. Publication types are real, everything else stays unknown and
        # is filled in when Europe PMC returns the same record.
        evidence_type=classify.evidence_type([], pub_types),
        study_design=classify.study_design(pub_types),
        is_oncology=None,
        access_level="not_accessed",
        publication_types=pub_types,
    )


async def search(query: str, *, limit: int = 25) -> list[RetrievedSource]:
    pmids = await _esearch(query, limit)
    if not pmids:
        return []
    await asyncio.sleep(POLITE_DELAY_SECONDS)
    return [_parse(summary) for summary in await _esummary(pmids) if summary.get("title")]
