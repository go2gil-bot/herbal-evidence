"""The pilot questionnaire.

Four questions, asked before and after reading the response. They target the
four things the pilot is actually about:

  1. what the review concluded
  2. how certain that conclusion is
  3. whether the findings were in humans
  4. whether a dose described in a study is a recommendation for the reader

Question 4 has one correct answer for every review, always. The other three
depend on the specific response, which is why a researcher approves an answer
key per version.

The questionnaire is versioned. A change to any wording is a new version, so
answers collected under different wordings are never pooled.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

QUESTIONNAIRE_VERSION = "2026-09-17.1"


class Option(BaseModel):
    id: str
    text: str


class Question(BaseModel):
    id: str
    text: str
    help: str = ""
    options: list[Option]


QUESTIONS: list[Question] = [
    Question(
        id="conclusion",
        text="מה הסקירה מסכמת לגבי הצמח ושיפור תיאבון?",
        options=[
            Option(id="benefit", text="נמצאה תועלת לשיפור תיאבון"),
            Option(id="no_benefit", text="נבדק ולא נמצאה תועלת"),
            Option(id="insufficient", text="אין מספיק ראיות מבני אדם כדי לקבוע"),
            Option(id="unsure", text="לא הצלחתי להבין מהתשובה"),
        ],
    ),
    Question(
        id="certainty",
        text="עד כמה בטוחים בממצא הזה?",
        help="כלומר: כמה חזקות הראיות שעליהן הוא נשען.",
        options=[
            Option(id="high", text="בטוחים מאוד"),
            Option(id="moderate", text="בטוחים במידה בינונית"),
            Option(id="low", text="לא בטוחים — הראיות חלשות"),
            Option(id="unsure", text="לא הצלחתי להבין מהתשובה"),
        ],
    ),
    Question(
        id="humans",
        text="הממצאים שבתשובה — האם הם ממחקרים בבני אדם?",
        options=[
            Option(id="humans", text="כן, בבני אדם"),
            Option(id="animals_only", text="לא, רק בבעלי חיים או במעבדה"),
            Option(id="mixed", text="חלקם בבני אדם וחלקם לא"),
            Option(id="unsure", text="לא הצלחתי להבין מהתשובה"),
        ],
    ),
    Question(
        id="dose_is_not_advice",
        text="בתשובה מופיע מינון שנבדק במחקר. האם זו המלצה עבורך?",
        help="השאלה הזו בודקת הבנה של מה שהתשובה אומרת, לא ידע רפואי.",
        options=[
            Option(id="yes_recommendation", text="כן, זו המלצה למינון שכדאי לקחת"),
            Option(id="study_detail_only", text="לא, זה תיאור של מה שנעשה במחקר"),
            Option(id="ask_doctor", text="לא בטוח/ה — צריך לשאול את הצוות המטפל"),
            Option(id="unsure", text="לא הצלחתי להבין מהתשובה"),
        ],
    ),
]

# The one answer that never depends on the review. A study's dose is a study
# detail, in every response this platform will ever publish.
FIXED_ANSWERS: dict[str, str] = {"dose_is_not_advice": "study_detail_only"}

QUESTION_IDS = {question.id for question in QUESTIONS}
Phase = Literal["pre", "post"]


class AssessmentSubmission(BaseModel):
    response_version_id: int
    phase: Phase
    # {question_id: option_id}
    answers: dict[str, str]
    participant_category: Literal["patient", "caregiver"] | None = None

    def validate_shape(self) -> None:
        unknown = set(self.answers) - QUESTION_IDS
        if unknown:
            raise ValueError(f"unknown question ids: {sorted(unknown)}")
        by_id = {question.id: {option.id for option in question.options} for question in QUESTIONS}
        for question_id, option_id in self.answers.items():
            if option_id not in by_id[question_id]:
                raise ValueError(f"{option_id!r} is not an option for {question_id!r}")


class AnswerKey(BaseModel):
    """What a researcher says the correct answers are for one response version."""

    answers: dict[str, str] = Field(min_length=1)

    def validate_shape(self) -> None:
        unknown = set(self.answers) - QUESTION_IDS
        if unknown:
            raise ValueError(f"unknown question ids: {sorted(unknown)}")
        for question_id, expected in FIXED_ANSWERS.items():
            if self.answers.get(question_id) not in (None, expected):
                raise ValueError(
                    f"{question_id!r} is always {expected!r} - a study dose is never a recommendation"
                )


def score(answers: dict[str, str], key: dict[str, str]) -> tuple[int, int]:
    """Count correct answers against the key. Only keyed questions count."""
    keyed = {**key, **FIXED_ANSWERS}
    scored = [q for q in keyed if q in answers]
    correct = sum(1 for q in scored if answers[q] == keyed[q])
    return correct, len(scored)
