from dataclasses import dataclass, field
from typing import Any


SEVERITY_RANK = {
    "low": 1,
    "moderate": 2,
    "high": 3,
    "critical": 4,
}


@dataclass(frozen=True)
class Medication:
    drug: str
    dose_mg: float | None = None
    frequency: str | None = None
    dose_unit: str = "mg"
    route: str | None = None
    formulation: str | None = None
    administration: str | None = None


@dataclass(frozen=True)
class Patient:
    id: str = "anonymous"
    age: int | None = None
    sex: str | None = None
    weight_kg: float | None = None
    scr_umol_l: float | None = None
    egfr: float | None = None
    crcl: float | None = None
    allergies: list[dict[str, Any]] = field(default_factory=list)
    diagnoses: list[str] = field(default_factory=list)
    labs: list[dict[str, Any]] = field(default_factory=list)
    encounter_id: str | None = None
    review_time: str | None = None


@dataclass(frozen=True)
class Prescription:
    id: str
    patient: Patient
    medications: list[Medication]
    review_targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class Indicator:
    name: str
    value: Any
    kind: str
    severity: str = "low"
    source: str = "emr"
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rule:
    id: str
    drug: str
    section: str
    condition_text: str
    action_text: str
    severity: str
    rule_type: str
    keywords: tuple[str, ...]
    threshold: float | None = None
    threshold_operator: str | None = None
    high_risk: bool = False
    lab_name: str | None = None
    lab_unit: str | None = None
    max_age_days: int | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MatchResult:
    rule_id: str
    indicator_name: str
    matched: bool
    expert: str
    confidence: float
    reason: str
    severity: str
    action: str
    provenance: dict[str, Any]
    fallback_used: bool = False
    disagreement: bool = False
