"""One shape for a retrieved record, whatever provider it came from."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

EvidenceType = Literal["human", "animal", "in_vitro", "review", "other"]
AccessLevel = Literal["full_text", "abstract_only", "not_accessed"]


@dataclass
class RetrievedSource:
    provider: str
    title: str

    pmid: str | None = None
    doi: str | None = None
    pmcid: str | None = None

    journal: str | None = None
    publication_year: int | None = None
    abstract: str | None = None

    # Labelling, derived from curated metadata rather than from the title.
    evidence_type: EvidenceType = "other"
    study_design: str | None = None
    # None means the metadata did not say. That is different from False.
    is_oncology: bool | None = None
    access_level: AccessLevel = "abstract_only"

    mesh_terms: list[str] = field(default_factory=list)
    publication_types: list[str] = field(default_factory=list)

    @property
    def identifier(self) -> tuple[str, str]:
        """The identity used for deduplication and for the unique constraint."""
        if self.pmid:
            return ("pmid", self.pmid)
        if self.doi:
            return ("doi", self.doi.lower())
        if self.pmcid:
            return ("pmcid", self.pmcid)
        # No stable identifier: fall back to the title so two copies of the same
        # untitled-by-id record still collapse into one.
        return ("manual", self.title.strip().lower()[:200])

    def to_row(self) -> dict:
        kind, value = self.identifier
        return {
            "id_kind": kind,
            "external_id": value,
            "title": self.title,
            "journal": self.journal,
            "publication_year": self.publication_year,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/" if self.pmid else None,
            "evidence_type": self.evidence_type,
            "study_design": self.study_design,
            "is_oncology": self.is_oncology,
            "access_level": self.access_level,
            "file_provenance": f"retrieved from {self.provider}",
        }
