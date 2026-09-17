"""Labelling, deduplication, SSRF and the draft contract.

These run offline. The live providers are exercised separately by
supabase/tests/literature_search.py, because a unit test that needs the internet
fails for reasons that have nothing to do with the code.
"""

from __future__ import annotations

import pytest

from app.ai.schema import DraftBody, validate_claims_cite_supplied_sources
from app.research import classify, dedupe, query
from app.research.europepmc import clean_title
from app.research.http import ALLOWED_HOSTS, FetchRefused, check_url
from app.research.models import RetrievedSource


def source(**overrides) -> RetrievedSource:
    row = {"provider": "europepmc", "title": "A study"}
    row.update(overrides)
    return RetrievedSource(**row)


# ------------------------------------------------------------- classification


def test_a_rodent_study_is_labelled_animal():
    assert classify.evidence_type(["Animals", "Mice", "Curcumin"], ["Journal Article"]) == "animal"


def test_a_human_study_is_labelled_human():
    assert classify.evidence_type(["Humans", "Adult"], ["Randomized Controlled Trial"]) == "human"


def test_a_study_with_both_arms_is_not_demoted_to_animal():
    # Comparative work indexed with Humans and Animals: the human arm is what
    # this product is about, so it must not be filed as an animal study.
    assert classify.evidence_type(["Humans", "Animals", "Mice"], ["Journal Article"]) == "human"


def test_cell_culture_is_labelled_in_vitro():
    assert classify.evidence_type(["Cells, Cultured", "In Vitro Techniques"], []) == "in_vitro"


def test_unindexed_metadata_does_not_produce_a_confident_label():
    assert classify.evidence_type([], ["Journal Article"]) == "other"


def test_the_most_specific_design_wins():
    types = ["Journal Article", "Randomized Controlled Trial", "Comparative Study"]
    assert classify.study_design(types) == "randomized controlled trial"


def test_oncology_is_unknown_rather_than_false_when_unindexed():
    # An unindexed record is not evidence that the study was outside oncology.
    assert classify.is_oncology([]) is None
    assert classify.is_oncology(["Neoplasms", "Humans"]) is True
    assert classify.is_oncology(["Diabetes Mellitus", "Humans"]) is False


def test_access_is_never_upgraded_beyond_what_was_reported():
    assert classify.access_level(in_epmc=False, is_open_access=True, has_abstract=True) == "abstract_only"
    assert classify.access_level(in_epmc=True, is_open_access=True, has_abstract=True) == "full_text"
    assert classify.access_level(in_epmc=False, is_open_access=False, has_abstract=False) == "not_accessed"


def test_markup_never_reaches_a_title():
    assert clean_title("Turmeric (&lt;i&gt;curcuma longa&lt;/i&gt;) rhizome.") == "Turmeric (curcuma longa) rhizome"


# --------------------------------------------------------------- deduplication


def test_the_same_pmid_from_two_providers_becomes_one_record():
    merged = dedupe.deduplicate(
        [
            source(provider="pubmed", pmid="123", title="A study", study_design="clinical trial"),
            source(provider="europepmc", pmid="123", title="A study", abstract="text",
                   mesh_terms=["Humans"], publication_types=["Randomized Controlled Trial"]),
        ]
    )
    assert len(merged) == 1
    assert merged[0].provider == "europepmc+pubmed"


def test_merging_recomputes_the_label_from_the_combined_metadata():
    # PubMed alone could not tell; Europe PMC's MeSH headings can.
    merged = dedupe.deduplicate(
        [
            source(provider="pubmed", pmid="123", evidence_type="other"),
            source(provider="europepmc", pmid="123", mesh_terms=["Animals", "Rats"]),
        ]
    )
    assert merged[0].evidence_type == "animal"


def test_merging_takes_the_better_access_level_but_invents_nothing():
    merged = dedupe.deduplicate(
        [
            source(provider="pubmed", pmid="123", access_level="not_accessed"),
            source(provider="europepmc", pmid="123", access_level="abstract_only"),
        ]
    )
    assert merged[0].access_level == "abstract_only"


def test_two_different_studies_stay_two():
    merged = dedupe.deduplicate([source(pmid="1"), source(pmid="2")])
    assert len(merged) == 2


def test_a_review_alongside_a_trial_raises_an_overlap_note():
    note = dedupe.overlap_note([source(pmid="1", evidence_type="review"),
                                source(pmid="2", evidence_type="human")])
    assert note and "חפיפה" in note


def test_no_overlap_note_when_there_is_nothing_to_double_count():
    assert dedupe.overlap_note([source(pmid="1", evidence_type="human")]) is None


# ------------------------------------------------------------------- queries


def test_the_query_never_widens_the_outcome_to_weight_or_intake():
    text = query.build(herb_terms=["Curcuma longa"])
    assert "appetite" in text
    # Folding these in would quietly turn a weight study into an appetite finding.
    assert "weight" not in text.lower() and "intake" not in text.lower()


def test_nothing_medical_is_added_that_the_user_did_not_supply():
    text = query.build(herb_terms=["Curcuma longa"])
    assert "cancer" not in text.lower() and "chemotherapy" not in text.lower()


def test_hebrew_aliases_are_not_sent_to_english_indexes():
    terms = query.terms_for_plant("Curcuma longa", ["כורכום", "turmeric"], "כורכום")
    assert terms == ["Curcuma longa", "turmeric"]


def test_a_search_without_a_usable_name_is_refused():
    with pytest.raises(ValueError):
        query.build(herb_terms=[])


# ---------------------------------------------------------------------- SSRF


def test_only_the_two_providers_are_reachable():
    assert ALLOWED_HOSTS == {"eutils.ncbi.nlm.nih.gov", "www.ebi.ac.uk"}


@pytest.mark.parametrize(
    "url",
    [
        "http://www.ebi.ac.uk/x",  # not https
        "https://example.com/x",  # not a provider
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata
        "https://localhost/x",
        "https://www.ebi.ac.uk.evil.test/x",  # suffix trick
    ],
)
def test_everything_else_is_refused(url):
    with pytest.raises(FetchRefused):
        check_url(url)


# --------------------------------------------------------- the draft contract


def a_valid_body(**overrides) -> dict:
    body = {
        "question": "האם כורכום משפר תיאבון?",
        "conclusion": "אין מספיק ראיות מבני אדם כדי להעריך תועלת לשיפור תיאבון.",
        "certainty": "נמוכה",
        "certainty_explanation": "שני מחקרים קטנים, מדידה לא אחידה.",
        "safety": "לא נמצא מידע על שילוב עם הטיפול שצוין.",
        "limitations": "מדגמים קטנים.",
        "claims": [],
    }
    body.update(overrides)
    return body


def test_a_well_formed_draft_validates():
    assert DraftBody.model_validate(a_valid_body()).certainty == "נמוכה"


def test_a_numeric_score_is_rejected():
    with pytest.raises(ValueError):
        DraftBody.model_validate(a_valid_body(conclusion="יעילות 8/10 לשיפור תיאבון"))


def test_calling_the_rating_grade_is_rejected():
    with pytest.raises(ValueError):
        DraftBody.model_validate(a_valid_body(certainty_explanation="רמת הוודאות נמוכה (GRADE Low)"))


def test_claiming_prisma_is_rejected():
    with pytest.raises(ValueError):
        DraftBody.model_validate(a_valid_body(limitations="הסקירה בוצעה לפי PRISMA"))


def test_an_invented_certainty_word_is_rejected():
    with pytest.raises(ValueError):
        DraftBody.model_validate(a_valid_body(certainty="בינונית-גבוהה"))


def test_inferring_safety_from_an_absence_of_reports_is_rejected():
    with pytest.raises(ValueError):
        DraftBody.model_validate(
            a_valid_body(safety="לא דווחו תופעות לוואי ולכן התכשיר בטוח לשימוש.")
        )


def test_reporting_that_nothing_was_reported_is_allowed():
    # The finding itself is fine. Only the inference from it is not.
    DraftBody.model_validate(
        a_valid_body(safety="לא דווחו תופעות לוואי במחקרים שנבדקו. אין מידע על שילוב עם הטיפול.")
    )


def test_saying_there_is_not_enough_information_to_call_it_safe_is_allowed():
    DraftBody.model_validate(
        a_valid_body(safety="לא נמצא מידע מספיק כדי לקבוע שהתכשיר בטוח בשילוב עם הטיפול שצוין.")
    )


def test_a_claim_citing_a_source_that_was_never_supplied_is_rejected():
    body = DraftBody.model_validate(
        a_valid_body(claims=[{"text": "לא נמצא הבדל", "source_id": "999",
                              "support_location": "abstract, sentence 2"}])
    )
    with pytest.raises(ValueError, match="not among the sources supplied"):
        validate_claims_cite_supplied_sources(body, allowed_ids={"1", "2"})


def test_a_claim_citing_a_supplied_source_passes():
    body = DraftBody.model_validate(
        a_valid_body(claims=[{"text": "לא נמצא הבדל", "source_id": "1",
                              "support_location": "abstract, sentence 2"}])
    )
    validate_claims_cite_supplied_sources(body, allowed_ids={"1", "2"})


def test_a_claim_without_a_support_location_cannot_be_built():
    with pytest.raises(ValueError):
        DraftBody.model_validate(
            a_valid_body(claims=[{"text": "טענה", "source_id": "1", "support_location": ""}])
        )
