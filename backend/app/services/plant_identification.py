"""Resolve what the user typed to a plant in the catalogue.

Three outcomes, and only three:

  resolved   - exactly one plant matched
  ambiguous  - several plants matched, so the USER picks
  not_found  - nothing matched, so a HUMAN looks at it

There is no fourth outcome where the system guesses. An unresolved name is a
legitimate result that goes to human review, not a failure to paper over.
"""

from __future__ import annotations

import re
import unicodedata

from app.domain.schemas import IdentificationResult, PlantCandidate
from app.services.supabase_client import SupabaseClient

# Hebrew geresh/gershayim have several Unicode spellings; users type all of them.
_PUNCTUATION = {
    "׳": "'",  # HEBREW PUNCTUATION GERESH
    "״": '"',  # HEBREW PUNCTUATION GERSHAYIM
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
}


def normalize(value: str) -> str:
    """Fold the spelling differences that should not change a match."""
    text = unicodedata.normalize("NFKC", value).strip().lower()
    for source, target in _PUNCTUATION.items():
        text = text.replace(source, target)
    # Hebrew niqqud and other combining marks.
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text)


async def identify(client: SupabaseClient, query: str) -> IdentificationResult:
    normalized = normalize(query)
    if not normalized:
        return IdentificationResult(outcome="not_found", query=query)

    rows = await client.select(
        "plant_aliases",
        columns="alias,language,plant_id,plants(scientific_name)",
        limit=200,
    )

    exact: list[dict] = []
    partial: list[dict] = []
    for row in rows:
        alias = normalize(row["alias"])
        if alias == normalized:
            exact.append(row)
        elif normalized in alias or alias in normalized:
            partial.append(row)

    matches = exact or partial
    if not matches:
        return IdentificationResult(outcome="not_found", query=query)

    aliases_by_plant: dict[int, list[str]] = {}
    for row in rows:
        aliases_by_plant.setdefault(row["plant_id"], []).append(row["alias"])

    seen: dict[int, PlantCandidate] = {}
    for row in matches:
        plant_id = row["plant_id"]
        if plant_id in seen:
            continue
        seen[plant_id] = PlantCandidate(
            plant_id=plant_id,
            scientific_name=(row.get("plants") or {}).get("scientific_name", ""),
            matched_alias=row["alias"],
            language=row["language"],
            aliases=sorted(set(aliases_by_plant.get(plant_id, []))),
        )

    candidates = sorted(seen.values(), key=lambda c: c.scientific_name)
    outcome = "resolved" if len(candidates) == 1 else "ambiguous"
    return IdentificationResult(outcome=outcome, query=query, candidates=candidates)
