from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "prescription_mcp/data/drug_domains_12.json"
OUTPUT = ROOT / "prescription_mcp/data/drug_domains_19.json"
RAW_OUTPUT = ROOT / "data/public/raw/lab_domain_openfda_labels.json"

EXISTING_LABS = {
    "ceftazidime": ("egfr", "mL/min/1.73m2", 7),
    "metformin": ("egfr", "mL/min/1.73m2", 7),
    "enoxaparin": ("crcl", "mL/min", 7),
    "gabapentin": ("crcl", "mL/min", 7),
}

DOMAINS = [
    {
        "canonical_name": "dofetilide",
        "generic_name": "DOFETILIDE",
        "aliases": ["dofetilide", "tikosyn"],
        "pattern": r"creatinine clearance[^.]{0,260}<\s*20\s*mL/min[^.]{0,120}contraindicated",
        "sections": ["dosage_and_administration", "contraindications"],
        "rule": {
            "id": "DOFE-CRCL-001", "section": "Dosage and Administration",
            "condition_text": "Dofetilide requires pharmacist review when creatinine clearance is below 20 mL/min.",
            "action_text": "Escalate for renal contraindication review.", "severity": "critical",
            "rule_type": "numeric", "keywords": ["crcl", "renal", "dose"],
            "threshold": 20.0, "threshold_operator": "<", "high_risk": True,
            "lab_name": "crcl", "lab_unit": "mL/min", "max_age_days": 7,
        },
    },
    {
        "canonical_name": "spironolactone",
        "generic_name": "SPIRONOLACTONE",
        "aliases": ["spironolactone", "aldactone"],
        "pattern": r"serum potassium[^.]{0,180}(?:≤|<=)\s*5\.0\s*mEq/L",
        "sections": ["dosage_and_administration", "warnings_and_cautions"],
        "rule": {
            "id": "SPIR-K-001", "section": "Dosage and Administration",
            "condition_text": "For the benchmark heart-failure initiation scenario, spironolactone requires review when serum potassium is above 5.0 mEq/L.",
            "action_text": "Escalate before initiation because the label criterion is not met.", "severity": "high",
            "rule_type": "numeric", "keywords": ["potassium", "hyperkalemia", "initiation"],
            "threshold": 5.0, "threshold_operator": ">", "high_risk": True,
            "lab_name": "potassium", "lab_unit": "mEq/L", "max_age_days": 7,
        },
    },
    {
        "canonical_name": "clozapine",
        "generic_name": "CLOZAPINE",
        "aliases": ["clozapine", "clozaril"],
        "pattern": r"ANC[^.]{0,180}less than\s*1500/(?:µ|μ|u)?L",
        "sections": ["dosage_and_administration", "warnings_and_cautions"],
        "rule": {
            "id": "CLOZ-ANC-001", "section": "Dosage and Administration",
            "condition_text": "In benchmark cases without documented BEN, clozapine initiation requires review when ANC is below 1500/uL.",
            "action_text": "Escalate for neutropenia and eligibility review.", "severity": "critical",
            "rule_type": "numeric", "keywords": ["anc", "neutropenia", "initiation"],
            "threshold": 1500.0, "threshold_operator": "<", "high_risk": True,
            "lab_name": "anc", "lab_unit": "/uL", "max_age_days": 7,
        },
    },
    {
        "canonical_name": "heparin",
        "generic_name": "HEPARIN SODIUM",
        "aliases": ["heparin", "heparin sodium"],
        "pattern": r"platelet count[^.]{0,180}(?:below|less than)\s*100,?000/mm",
        "sections": ["warnings_and_cautions", "dosage_and_administration"],
        "rule": {
            "id": "HEPA-PLT-001", "section": "Warnings and Precautions",
            "condition_text": "Heparin requires immediate review when platelet count is below 100000/uL.",
            "action_text": "Escalate for heparin discontinuation and HIT assessment.", "severity": "critical",
            "rule_type": "numeric", "keywords": ["platelets", "hit", "thrombocytopenia"],
            "threshold": 100000.0, "threshold_operator": "<", "high_risk": True,
            "lab_name": "platelets", "lab_unit": "/uL", "max_age_days": 3,
        },
    },
    {
        "canonical_name": "lithium carbonate",
        "generic_name": "LITHIUM CARBONATE",
        "aliases": ["lithium", "lithium carbonate"],
        "pattern": r"toxic concentrations for lithium[^.]{0,100}(?:≥|>=)\s*1\.5\s*mEq/L",
        "sections": ["warnings_and_cautions", "boxed_warning"],
        "rule": {
            "id": "LITH-LVL-001", "section": "Warnings and Precautions",
            "condition_text": "Lithium requires urgent review when serum concentration is at least 1.5 mEq/L.",
            "action_text": "Escalate for suspected lithium toxicity.", "severity": "critical",
            "rule_type": "numeric", "keywords": ["lithium", "toxicity", "concentration"],
            "threshold": 1.5, "threshold_operator": ">=", "high_risk": True,
            "lab_name": "lithium", "lab_unit": "mEq/L", "max_age_days": 3,
        },
    },
    {
        "canonical_name": "linezolid",
        "generic_name": "LINEZOLID",
        "aliases": ["linezolid", "zyvox"],
        "pattern": r"Monitor complete blood counts weekly",
        "sections": ["warnings_and_cautions"],
        "rule": {
            "id": "LINE-CBC-001", "section": "Warnings and Precautions",
            "condition_text": "Linezolid review requires a weekly complete blood count; an abnormal or unavailable result is escalated.",
            "action_text": "Escalate incomplete or abnormal hematologic monitoring.", "severity": "high",
            "rule_type": "monitoring", "keywords": ["cbc", "myelosuppression", "monitoring"],
            "high_risk": True, "lab_name": "cbc", "lab_unit": "status", "max_age_days": 7,
        },
    },
    {
        "canonical_name": "divalproex sodium",
        "generic_name": "DIVALPROEX SODIUM",
        "aliases": ["divalproex", "divalproex sodium", "valproate"],
        "pattern": r"Serum liver tests should be performed prior to therapy",
        "sections": ["warnings_and_cautions", "boxed_warning"],
        "rule": {
            "id": "VALP-LFT-001", "section": "Warnings and Precautions",
            "condition_text": "For the benchmark initiation scenario, divalproex review requires a pretherapy liver-function panel; an abnormal or unavailable result is escalated.",
            "action_text": "Escalate incomplete or abnormal hepatic assessment.", "severity": "high",
            "rule_type": "monitoring", "keywords": ["lft", "hepatic", "monitoring", "initiation"],
            "high_risk": True, "lab_name": "lft", "lab_unit": "status", "max_age_days": 30,
        },
    },
]


def fetch(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "PrescriptionMCPResearch/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def find_match(record: dict, config: dict) -> tuple[str, str] | None:
    pattern = re.compile(config["pattern"], re.IGNORECASE)
    for section in config["sections"]:
        text = " ".join(record.get(section, []))
        match = pattern.search(text)
        if match:
            excerpt = " ".join(text[max(0, match.start() - 140):min(len(text), match.end() + 220)].split())
            return section, excerpt
    return None


def metadata(record: dict, url: str, section: str, excerpt: str) -> dict:
    openfda = record.get("openfda", {})
    return {
        "source": "openFDA Drug Label API", "set_id": str(record.get("set_id", "")),
        "version": str(record.get("version", "")), "effective_date": str(record.get("effective_time", "")),
        "manufacturer": (openfda.get("manufacturer_name") or [""])[0], "source_url": url,
        "source_field": section, "source_span": excerpt,
    }


def main() -> None:
    combined = deepcopy(json.loads(BASE.read_text(encoding="utf-8")))
    combined["schema_version"] = "3.0-public-19-domain-with-lab-evidence"
    for domain in combined["domains"]:
        if domain["canonical_name"] in EXISTING_LABS:
            lab_name, unit, age = EXISTING_LABS[domain["canonical_name"]]
            domain["rules"][0].update({"lab_name": lab_name, "lab_unit": unit, "max_age_days": age})
    raw = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "domains": []}
    for config in DOMAINS:
        query = urllib.parse.quote(f'openfda.generic_name.exact:"{config["generic_name"]}"')
        url = f"https://api.fda.gov/drug/label.json?search={query}&limit=100"
        payload = fetch(url)
        selected = []
        for record in payload.get("results", []):
            matched = find_match(record, config)
            if not matched:
                continue
            item = metadata(record, url, *matched)
            if any(item["set_id"] == prior["set_id"] or item["manufacturer"] == prior["manufacturer"] for prior in selected):
                continue
            selected.append(item)
            if len(selected) == 2:
                break
        if len(selected) != 2:
            raise RuntimeError(f'{config["canonical_name"]}: found {len(selected)} independent labels')
        primary, external = selected
        rule = deepcopy(config["rule"])
        rule["source_field"] = primary.pop("source_field")
        rule["source_span"] = primary.pop("source_span")
        rule["external_source_field"] = external.pop("source_field")
        rule["external_source_span"] = external.pop("source_span")
        combined["domains"].append({
            "canonical_name": config["canonical_name"], "aliases": config["aliases"],
            "validation_status": "public_lab_validation", "required_fields": ["dose_mg", "frequency"],
            "label": primary, "external_label": external, "rules": [rule],
        })
        raw["domains"].append({"canonical_name": config["canonical_name"], "request": url, "primary": primary, "external": external})
    OUTPUT.write_text(json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8")
    RAW_OUTPUT.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUTPUT} with {len(combined['domains'])} domains")


if __name__ == "__main__":
    main()
