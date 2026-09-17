"""The output contract for a generated draft.

The model is not free to return prose. It returns this shape or the result is
rejected, and the rules the product cares about are validators here rather than
politely-worded requests in a prompt:

  * no numeric effectiveness score anywhere
  * the certainty label is a word, and "GRADE" is not one of the allowed words
  * every claim names the source it came from
  * a source id that was not supplied is a rejection, not a citation
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

# Words a reviewer may see as the certainty label. A number is not one of them,
# and neither is "GRADE" - that name means a methodology this product has not
# implemented.
ALLOWED_CERTAINTY = {
    "גבוהה",
    "בינונית",
    "נמוכה",
    "נמוכה מאוד",
    "לא ניתן להעריך",
}

FORBIDDEN_PATTERNS = [
    (re.compile(r"\b\d+\s*/\s*10\b"), "numeric score"),
    (re.compile(r"\b\d+\s*מתוך\s*10\b"), "numeric score"),
    (re.compile(r"\bGRADE\b", re.IGNORECASE), "GRADE label"),
    (re.compile(r"\bPRISMA\b", re.IGNORECASE), "PRISMA claim"),
]


def _reject_forbidden(text: str, where: str) -> str:
    for pattern, what in FORBIDDEN_PATTERNS:
        if pattern.search(text):
            raise ValueError(f"{where} contains a {what}, which this product does not use")
    return text


class Claim(BaseModel):
    text: str = Field(min_length=1)
    # The identifier of a source that was actually supplied to the model.
    source_id: str = Field(min_length=1)
    # Where in that source the claim is supported.
    support_location: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def no_forbidden_language(cls, value: str) -> str:
        return _reject_forbidden(value, "a claim")


class DraftBody(BaseModel):
    question: str = Field(min_length=1)
    conclusion: str = Field(min_length=1)
    certainty: str
    certainty_explanation: str = Field(min_length=1)
    relevance: str = ""
    not_studied: str = ""
    appetite_results: str = ""
    secondary_outcomes: str = ""
    safety: str = Field(min_length=1)
    limitations: str = Field(min_length=1)
    preclinical: str = ""
    claims: list[Claim] = Field(default_factory=list)

    @field_validator("certainty")
    @classmethod
    def certainty_is_an_allowed_word(cls, value: str) -> str:
        value = value.strip()
        if value not in ALLOWED_CERTAINTY:
            raise ValueError(
                f"certainty must be one of {sorted(ALLOWED_CERTAINTY)}, not {value!r}"
            )
        return value

    @field_validator("conclusion", "certainty_explanation", "safety", "limitations",
                     "appetite_results", "secondary_outcomes", "preclinical", "relevance",
                     "not_studied")
    @classmethod
    def no_forbidden_language(cls, value: str) -> str:
        return _reject_forbidden(value, "the draft")

    @model_validator(mode="after")
    def safety_must_not_infer_from_silence(self):
        """Catch "nothing was reported, therefore it is safe".

        Narrow on purpose. "No adverse events were reported" is a finding and is
        allowed; so is "there is not enough information to say it is safe". What
        is refused is the inference between them - an absence phrase, a
        connective, then a safety claim.

        This is a guard rail, not a substitute for the reviewer: a
        differently-worded version of the same inference gets through, which is
        one of the reasons every response is read by a person before it is
        published.
        """
        absence = r"(לא דווח\w*|אין דיווח\w*|לא נמצא\w*|לא תועד\w*)"
        connective = r"(ולכן|לכן|לפיכך|ומכאן|מכאן|משמע|ולפיכך)"
        safe_claim = r"(בטוח\w*|ללא סיכון|אין סיכון)"

        if re.search(rf"{absence}[^.]{{0,80}}{connective}[^.]{{0,80}}{safe_claim}", self.safety):
            raise ValueError(
                "safety infers safety from an absence of reports; "
                "state what was not reported instead of concluding it is safe"
            )
        return self


def validate_claims_cite_supplied_sources(body: DraftBody, allowed_ids: set[str]) -> None:
    """A citation to something that was not supplied is a fabrication."""
    for claim in body.claims:
        if claim.source_id not in allowed_ids:
            raise ValueError(
                f"claim cites source {claim.source_id!r}, which was not among the sources supplied"
            )


# The schema sent to the provider, so the model is told the shape instead of
# guessing it. Hand-written rather than derived from the Pydantic model: strict
# mode requires every property listed in `required` and `additionalProperties`
# false everywhere, and a generated schema carries keywords strict mode rejects.
#
# Pydantic still validates what comes back. The provider schema shapes the
# output; the validators are what refuse it.
RESPONSE_JSON_SCHEMA = {
    "name": "herbal_evidence_draft",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "question", "conclusion", "certainty", "certainty_explanation",
            "relevance", "not_studied", "appetite_results", "secondary_outcomes",
            "safety", "limitations", "preclinical", "claims",
        ],
        "properties": {
            "question": {"type": "string", "description": "השאלה שנבדקה, בעברית"},
            "conclusion": {
                "type": "string",
                "description": "מסקנה קצרה על תיאבון בלבד. אם אין די ראיות מבני אדם - זו המסקנה.",
            },
            "certainty": {"type": "string", "enum": sorted(ALLOWED_CERTAINTY)},
            "certainty_explanation": {
                "type": "string",
                "description": "כמות ואיכות המחקרים, עקביות, ישירוּת ומגבלות. בלי ציון מספרי ובלי המילה GRADE.",
            },
            "relevance": {"type": "string", "description": "מה רלוונטי לבקשה. ריק אם לא ידוע."},
            "not_studied": {"type": "string", "description": "מה לא נחקר בהקשר הזה. ריק אם לא ידוע."},
            "appetite_results": {
                "type": "string",
                "description": "תוצאות תיאבון בלבד, כולל איך נמדד. ריק אם לא דווח.",
            },
            "secondary_outcomes": {
                "type": "string",
                "description": "משקל, צריכת מזון, איכות חיים - בנפרד. אף פעם לא כראיה לתיאבון.",
            },
            "safety": {
                "type": "string",
                "description": "מבוסס מקורות. היעדר דיווח אינו בטיחות - אמור מה לא דווח.",
            },
            "limitations": {"type": "string", "description": "מגבלות, ממצאים סותרים, מידע חסר."},
            "preclinical": {
                "type": "string",
                "description": "מעבדה ובעלי חיים בלבד. לא ראיה לתועלת בבני אדם. ריק אם אין.",
            },
            "claims": {
                "type": "array",
                "description": "כל טענה מהותית, עם המקור והמיקום התומך. ריק אם אין טענות נתמכות.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["text", "source_id", "support_location"],
                    "properties": {
                        "text": {"type": "string"},
                        "source_id": {
                            "type": "string",
                            "description": "מזהה של מקור שסופק. אסור להמציא.",
                        },
                        "support_location": {
                            "type": "string",
                            "description": "עמוד/סעיף בטקסט מלא, או קטע מזוהה בתקציר.",
                        },
                    },
                },
            },
        },
    },
}
