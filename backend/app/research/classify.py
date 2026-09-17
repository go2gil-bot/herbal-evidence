"""Label a record from curated metadata, not from the words in its title.

MeSH headings and publication types are assigned by indexers, so they are the
honest basis for saying "this is an animal study". Guessing from a title would
be the kind of inference this product exists to avoid.

Everything here returns `None` or `"other"` rather than a confident wrong
answer when the metadata is silent. A researcher corrects it in the editor; the
system does not invent it.
"""

from __future__ import annotations

from app.research.models import AccessLevel, EvidenceType

# MeSH descriptors that settle the question of what was studied.
HUMAN_TERMS = {"humans", "adult", "middle aged", "aged", "child", "female", "male"}
ANIMAL_TERMS = {
    "animals", "mice", "rats", "rabbits", "dogs", "swine", "zebrafish",
    "disease models, animal", "rodentia", "mice, inbred c57bl",
}
IN_VITRO_TERMS = {
    "in vitro techniques", "cells, cultured", "cell line", "cell line, tumor",
    "hep g2 cells", "caco-2 cells",
}

# A publication type that describes the study design itself.
DESIGN_TYPES = {
    "randomized controlled trial": "randomized controlled trial",
    "clinical trial": "clinical trial",
    "clinical trial, phase i": "clinical trial phase I",
    "clinical trial, phase ii": "clinical trial phase II",
    "clinical trial, phase iii": "clinical trial phase III",
    "controlled clinical trial": "controlled clinical trial",
    "observational study": "observational study",
    "meta-analysis": "meta-analysis",
    "systematic review": "systematic review",
    "review": "review",
    "case reports": "case report",
    "comparative study": "comparative study",
}

REVIEW_TYPES = {"review", "systematic review", "meta-analysis"}

ONCOLOGY_HINTS = ("neoplasm", "carcinoma", "cancer", "tumor", "tumour", "oncolog", "lymphoma", "leukemia", "sarcoma")


def _lower(values: list[str]) -> set[str]:
    return {value.strip().lower() for value in values if value}


def evidence_type(mesh_terms: list[str], publication_types: list[str]) -> EvidenceType:
    mesh = _lower(mesh_terms)
    types = _lower(publication_types)

    if types & REVIEW_TYPES:
        return "review"

    has_human = bool(mesh & HUMAN_TERMS)
    has_animal = bool(mesh & ANIMAL_TERMS)

    # "Animals" plus "Humans" happens on comparative work; the human arm is what
    # matters for this product, so it is not demoted to an animal study.
    if has_human:
        return "human"
    if has_animal:
        return "animal"
    if mesh & IN_VITRO_TERMS:
        return "in_vitro"
    return "other"


def study_design(publication_types: list[str]) -> str | None:
    types = _lower(publication_types)
    # Most specific first: an RCT is also tagged "Journal Article".
    for key in (
        "randomized controlled trial",
        "meta-analysis",
        "systematic review",
        "clinical trial, phase iii",
        "clinical trial, phase ii",
        "clinical trial, phase i",
        "controlled clinical trial",
        "clinical trial",
        "observational study",
        "case reports",
        "review",
        "comparative study",
    ):
        if key in types:
            return DESIGN_TYPES[key]
    return None


def is_oncology(mesh_terms: list[str]) -> bool | None:
    """True, False, or None when the metadata does not say.

    None matters: an unindexed record is not evidence that the study was outside
    oncology. Only an indexed record with no oncology descriptor is.
    """
    if not mesh_terms:
        return None
    haystack = " ".join(mesh_terms).lower()
    return any(hint in haystack for hint in ONCOLOGY_HINTS)


def access_level(*, in_epmc: bool, is_open_access: bool, has_abstract: bool) -> AccessLevel:
    """What we can actually read - never an assumption that we can read more.

    Full text counts only when the provider says the text is available to us.
    Paywalled records stay `abstract_only`, and that label travels all the way to
    the reader.
    """
    if in_epmc and is_open_access:
        return "full_text"
    if has_abstract:
        return "abstract_only"
    return "not_accessed"
