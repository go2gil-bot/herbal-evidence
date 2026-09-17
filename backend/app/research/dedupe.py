"""Collapse the same record arriving from two providers.

Two things must not happen:

  1. The same study counted twice because PubMed and Europe PMC both returned
     it. They are merged on identifier, and the richer record wins field by
     field - Europe PMC carries MeSH headings and the abstract, PubMed does not.

  2. A trial and a review discussing that trial counted as two pieces of
     evidence. They are different records with different identifiers, so merging
     cannot catch it; instead reviews are flagged so the researcher sees the
     overlap rather than a larger-looking body of evidence.
"""

from __future__ import annotations

from app.research.models import RetrievedSource

# Field by field, a value beats no value; between two values the richer provider
# wins. Europe PMC is richer for everything it returns.
RICHER_PROVIDER = "europepmc"


def _merge(primary: RetrievedSource, other: RetrievedSource) -> RetrievedSource:
    winner, loser = (
        (primary, other) if primary.provider == RICHER_PROVIDER else (other, primary)
    )

    merged = RetrievedSource(
        provider=f"{winner.provider}+{loser.provider}",
        title=winner.title or loser.title,
        pmid=winner.pmid or loser.pmid,
        doi=winner.doi or loser.doi,
        pmcid=winner.pmcid or loser.pmcid,
        journal=winner.journal or loser.journal,
        publication_year=winner.publication_year or loser.publication_year,
        abstract=winner.abstract or loser.abstract,
        study_design=winner.study_design or loser.study_design,
        mesh_terms=winner.mesh_terms or loser.mesh_terms,
        publication_types=winner.publication_types or loser.publication_types,
    )

    # Labels are recomputed from the merged metadata rather than copied, so a
    # record that only became classifiable after merging gets the right label.
    from app.research import classify

    merged.evidence_type = classify.evidence_type(merged.mesh_terms, merged.publication_types)
    merged.is_oncology = classify.is_oncology(merged.mesh_terms)

    # Access is the better of the two: if either provider can give us full text,
    # we can read full text. It is never upgraded beyond what was reported.
    ranking = {"not_accessed": 0, "abstract_only": 1, "full_text": 2}
    merged.access_level = max(
        (winner.access_level, loser.access_level), key=lambda level: ranking[level]
    )
    return merged


def deduplicate(sources: list[RetrievedSource]) -> list[RetrievedSource]:
    by_identifier: dict[tuple[str, str], RetrievedSource] = {}
    for source in sources:
        key = source.identifier
        if key in by_identifier:
            by_identifier[key] = _merge(by_identifier[key], source)
        else:
            by_identifier[key] = source
    return list(by_identifier.values())


def overlap_note(sources: list[RetrievedSource]) -> str | None:
    """A sentence for the researcher when reviews and primary studies coexist.

    Not a computation of who cites whom - that needs the full text. It is a
    prompt to check, which is the honest thing a counter can do.
    """
    reviews = [s for s in sources if s.evidence_type == "review"]
    primary = [s for s in sources if s.evidence_type in {"human", "animal", "in_vitro"}]
    if reviews and primary:
        return (
            f"{len(reviews)} סקירות ו-{len(primary)} מחקרים ראשוניים באותה קבוצה. "
            "יש לבדוק חפיפה לפני ספירת ראיות - מחקר וסקירה שדנה בו אינם שתי ראיות."
        )
    return None
