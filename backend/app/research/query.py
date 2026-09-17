"""Build the search query from what the user actually supplied.

Nothing medical is invented here. If the request named no treatment, the query
carries no treatment. The only terms added are the ones that define the product's
question at all: the herb, and appetite as the outcome.
"""

from __future__ import annotations

# Appetite and its near neighbours in the literature. Weight and intake are NOT
# in this list - they are separate secondary outcomes, and folding them into the
# search would quietly turn a weight study into an appetite finding.
APPETITE_TERMS = [
    "appetite",
    "anorexia",
    "appetite stimulant",
    "cachexia",
]


def build(*, herb_terms: list[str], extra_context: list[str] | None = None) -> str:
    """A boolean query both providers understand.

    PubMed and Europe PMC both accept `(a OR b) AND (c OR d)`, so one string
    serves both and the two searches stay comparable.
    """
    herbs = [term.strip() for term in herb_terms if term and term.strip()]
    if not herbs:
        raise ValueError("a search needs at least one herb term")

    herb_clause = " OR ".join(f'"{term}"' for term in dict.fromkeys(herbs))
    appetite_clause = " OR ".join(f'"{term}"' for term in APPETITE_TERMS)

    query = f"({herb_clause}) AND ({appetite_clause})"

    for context in extra_context or []:
        context = context.strip()
        if context:
            query += f' AND "{context}"'
    return query


def terms_for_plant(scientific_name: str | None, aliases: list[str], typed: str) -> list[str]:
    """Which names to search for.

    The scientific name first, then Latin-script aliases. Hebrew aliases are
    dropped on purpose: the indexes are English, and a Hebrew token would only
    ever match nothing while making the query look more thorough than it is.
    """
    terms: list[str] = []
    if scientific_name:
        terms.append(scientific_name)
    for alias in aliases:
        if alias and alias.isascii():
            terms.append(alias)
    if not terms and typed.isascii():
        terms.append(typed)
    return terms
