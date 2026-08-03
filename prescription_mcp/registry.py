from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .models import Medication, Rule


class DrugDomainRegistry:
    def __init__(self, path: Path | None = None) -> None:
        expanded = Path(__file__).with_name("data") / "drug_domains_19.json"
        source = path or (expanded if expanded.exists() else Path(__file__).with_name("data") / "drug_domains_12.json")
        payload = json.loads(source.read_text(encoding="utf-8"))
        self.schema_version = payload["schema_version"]
        self.evidence_sections = tuple(payload["evidence_sections"])
        self.domains = {domain["canonical_name"]: domain for domain in payload["domains"]}
        self.aliases = {
            alias.lower().replace("-", " ").strip(): domain["canonical_name"]
            for domain in payload["domains"]
            for alias in domain["aliases"]
        }

    def resolve(self, name: str) -> dict | None:
        canonical = self.aliases.get(name.lower().replace("-", " ").strip())
        return self.domains.get(canonical) if canonical else None

    def normalize_medication(self, medication: Medication) -> Medication | None:
        domain = self.resolve(medication.drug)
        if domain is None or domain["validation_status"] not in {"sentinel_validated", "public_extended_validation", "public_lab_validation"}:
            return None
        updates = {"drug": domain["canonical_name"]}
        for field, value in domain.get("inferred_fields", {}).items():
            if getattr(medication, field) in {None, ""}:
                updates[field] = value
        return replace(medication, **updates)

    def validate_medication(self, medication: Medication) -> list[str]:
        domain = self.domains[medication.drug]
        return [field for field in domain.get("required_fields", []) if getattr(medication, field) in {None, ""}]

    def rules_for(self, canonical_names: list[str]) -> list[Rule]:
        rules = []
        for name in canonical_names:
            domain = self.domains[name]
            label = domain["label"]
            for raw in domain["rules"]:
                provenance = {
                    "source": label["source"],
                    "set_id": label["set_id"],
                    "version": label["version"],
                    "effective_date": label["effective_date"],
                    "manufacturer": label["manufacturer"],
                    "source_url": label["source_url"],
                    "section": raw["section"],
                    "source_span": raw["source_span"],
                }
                if domain.get("external_label"):
                    provenance["external_label"] = domain["external_label"]
                    provenance["external_source_span"] = raw.get("external_source_span", "")
                rules.append(Rule(
                    id=raw["id"],
                    drug=name,
                    section=raw["section"],
                    condition_text=raw["condition_text"],
                    action_text=raw["action_text"],
                    severity=raw["severity"],
                    rule_type=raw["rule_type"],
                    keywords=tuple(raw["keywords"]),
                    threshold=raw.get("threshold"),
                    threshold_operator=raw.get("threshold_operator"),
                    high_risk=raw.get("high_risk", False),
                    lab_name=raw.get("lab_name"),
                    lab_unit=raw.get("lab_unit"),
                    max_age_days=raw.get("max_age_days"),
                    provenance=provenance,
                ))
        return rules

    def describe(self, name: str) -> dict:
        domain = self.resolve(name)
        if domain is None:
            return {"covered": False, "drug": name}
        return {"covered": True, **domain}


def normalize_context_drug(name: str) -> str:
    text = name.lower().replace("-", " ").strip()
    aliases = {
        "warfarin sodium": "warfarin",
        "nsaid": "ibuprofen",
        "penicillin": "penicillin",
        "penicillin g": "penicillin",
        "nifedipine gits": "nifedipine extended release",
    }
    return aliases.get(text, text)
