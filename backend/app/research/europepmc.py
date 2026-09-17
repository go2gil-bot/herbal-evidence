"""Europe PMC REST adapter.

https://europepmc.org/RestfulWebService - the `core` result type returns MeSH
headings and publication types, which is what makes honest labelling possible.
"""

from __future__ import annotations

import html
import logging
import re

from app.research import classify
from app.research.http import get
from app.research.models import RetrievedSource

logger = logging.getLogger("herbal_evidence.research.europepmc")

PROVIDER = "europepmc"
SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


# Europe PMC returns titles with HTML-escaped markup, e.g.
# "Turmeric (&lt;i&gt;curcuma longa&lt;/i&gt;) rhizome". Stored as-is, that markup
# would end up in front of a reader.
_TAG = re.compile(r"<[^>]+>")


def clean_title(raw: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub("", html.unescape(raw or ""))).strip().rstrip(".")


def _flatten(container: dict | None, outer: str, inner: str) -> list[str]:
    if not container:
        return []
    values = container.get(inner) or []
    if not isinstance(values, list):
        return []
    if values and isinstance(values[0], dict):
        return [v.get("descriptorName") or v.get("name") or "" for v in values]
    return [str(v) for v in values]


def _parse(result: dict) -> RetrievedSource:
    mesh = _flatten(result.get("meshHeadingList"), "meshHeadingList", "meshHeading")
    pub_types = _flatten(result.get("pubTypeList"), "pubTypeList", "pubType")

    journal = ((result.get("journalInfo") or {}).get("journal") or {}).get("title")

    year = result.get("pubYear")
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None

    abstract = html.unescape(result.get("abstractText") or "") or None

    return RetrievedSource(
        provider=PROVIDER,
        title=clean_title(result.get("title")),
        pmid=result.get("pmid"),
        doi=result.get("doi"),
        pmcid=result.get("pmcid"),
        journal=journal,
        publication_year=year,
        abstract=abstract,
        evidence_type=classify.evidence_type(mesh, pub_types),
        study_design=classify.study_design(pub_types),
        is_oncology=classify.is_oncology(mesh),
        access_level=classify.access_level(
            in_epmc=result.get("inEPMC") == "Y",
            is_open_access=result.get("isOpenAccess") == "Y",
            has_abstract=bool(abstract),
        ),
        mesh_terms=mesh,
        publication_types=pub_types,
    )


async def search(query: str, *, limit: int = 25) -> list[RetrievedSource]:
    response = await get(
        SEARCH_URL,
        params={
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": str(min(limit, 100)),
        },
    )
    payload = response.json()
    results = (payload.get("resultList") or {}).get("result") or []
    return [_parse(result) for result in results if result.get("title")]
