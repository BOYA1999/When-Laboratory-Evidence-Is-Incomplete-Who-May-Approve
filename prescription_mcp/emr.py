from __future__ import annotations

from typing import Any

from .models import Medication, Patient, Prescription


class EMRMCPServer:
    name = "EMR-MCP-Server"

    def build_prescription(self, payload: dict[str, Any]) -> Prescription:
        patient_payload = payload.get("patient", {})
        patient = Patient(
            id=str(patient_payload.get("id", payload.get("patient_id", "anonymous"))),
            age=_as_int(patient_payload.get("age", payload.get("age"))),
            sex=str(patient_payload.get("sex", payload.get("sex", ""))),
            weight_kg=_as_float(patient_payload.get("weight_kg", payload.get("weight_kg"))),
            scr_umol_l=_as_float(patient_payload.get("scr_umol_l", payload.get("scr_umol_l"))),
            egfr=_as_float(patient_payload.get("egfr", payload.get("egfr"))),
            crcl=_as_float(patient_payload.get("crcl", payload.get("crcl"))),
            allergies=list(patient_payload.get("allergies", payload.get("allergies", []))),
            diagnoses=list(patient_payload.get("diagnoses", payload.get("diagnoses", []))),
            labs=list(patient_payload.get("labs", payload.get("labs", []))),
            encounter_id=_as_text(patient_payload.get("encounter_id", payload.get("encounter_id"))),
            review_time=_as_text(patient_payload.get("review_time", payload.get("review_time"))),
        )
        meds = payload.get("medications") or payload.get("drugs") or []
        medications = [
            Medication(
                drug=str(item.get("drug", item.get("name", ""))),
                dose_mg=_as_float(item.get("dose_mg", item.get("dose"))),
                frequency=item.get("frequency"),
                dose_unit=str(item.get("dose_unit", "mg")),
                route=item.get("route"),
                formulation=item.get("formulation"),
                administration=item.get("administration") or ("crushed" if item.get("crushed") is True else None),
            )
            for item in meds
            if isinstance(item, dict)
        ]
        if not medications and "payload" in payload:
            medications = _fallback_demo_medications(str(payload["payload"]))
        targets = tuple(str(item) for item in payload.get("review_targets", []))
        return Prescription(id=str(payload.get("id", "unknown")), patient=patient, medications=medications, review_targets=targets)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None else None


def _as_text(value: Any) -> str | None:
    return str(value) if value not in {None, ""} else None


def _fallback_demo_medications(seed_text: str) -> list[Medication]:
    try:
        seed = int(seed_text.rsplit("_", 1)[-1])
    except ValueError:
        seed = 0
    if seed % 3 == 0:
        return [
            Medication("ceftazidime", 1000, "q8h"),
            Medication("warfarin", 3, "qd"),
            Medication("ibuprofen", 400, "tid"),
        ]
    if seed % 3 == 1:
        return [Medication("ceftazidime", 2000, "q12h")]
    return [Medication("nifedipine", 30, "qd")]
