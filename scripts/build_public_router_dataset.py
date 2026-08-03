from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prescription_mcp.router_features import FEATURE_NAMES, extract_router_features


RAW = ROOT / "data" / "public" / "raw"
OUT = ROOT / "data" / "public" / "processed"
SECTIONS = {
    "dosage_and_administration": "Dosage and Administration",
    "contraindications": "Contraindications",
    "warnings": "Warnings and Precautions",
    "warnings_and_precautions": "Warnings and Precautions",
    "drug_interactions": "Drug Interactions",
    "indications_and_usage": "Indications and Usage",
    "use_in_specific_populations": "Special Populations",
    "geriatric_use": "Special Populations",
    "pediatric_use": "Special Populations",
    "pregnancy": "Special Populations",
}
NUMBER_WITH_UNIT = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|hours?|days?|weeks?|years?|kg|mmhg|inr|ml/min|%)\b", re.I)
COMPLEX = re.compile(r"concomitant|concurrently|inhibitor|inducer|monitor|individuali[sz]e|unless|except|interaction|multiple", re.I)


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if 45 <= len(part.strip()) <= 600]


def policy_label(section: str, text: str) -> str:
    if "Dosage" in section and NUMBER_WITH_UNIT.search(text):
        return "ExpertA"
    complexity = len(re.findall(r"[,;:]|\b(?:and|or|if|unless|except)\b", text, re.I))
    if "Interaction" in section or COMPLEX.search(text) or complexity >= 5 or len(text) > 260:
        return "ExpertC"
    return "ExpertB"


def load_rules() -> list[dict]:
    payload = json.loads((RAW / "openfda_labels_200.json").read_text(encoding="utf-8-sig"))
    rules = []
    for label in payload["results"]:
        set_id = label.get("set_id", "unknown")
        drug = (label.get("openfda", {}).get("generic_name") or label.get("openfda", {}).get("brand_name") or ["unknown"])[0]
        for key, section in SECTIONS.items():
            for block in label.get(key, []):
                for sentence in split_sentences(block):
                    digest = hashlib.sha256(f"{set_id}|{key}|{sentence}".encode()).hexdigest()[:16]
                    severity = "high" if section in {"Contraindications", "Warnings and Precautions", "Drug Interactions"} else "moderate"
                    rules.append({
                        "group_id": digest,
                        "set_id": set_id,
                        "drug": drug,
                        "section": section,
                        "rule_text": sentence,
                        "severity": severity,
                        "expert_label": policy_label(section, sentence),
                    })
    unique = {rule["group_id"]: rule for rule in rules}
    return sorted(unique.values(), key=lambda row: row["group_id"])


def load_indicators() -> dict[str, list[tuple[str, object]]]:
    pools = {"numeric": [], "semantic": [], "complex": []}
    with zipfile.ZipFile(RAW / "synthea_sample_data_csv_apr2020.zip") as archive:
        with archive.open("csv/observations.csv") as handle:
            for row in csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig")):
                value = row.get("VALUE", "")
                try:
                    number = float(value)
                except ValueError:
                    continue
                pools["numeric"].append((f"{row.get('DESCRIPTION', 'observation')} {value} {row.get('UNITS', '')}".strip(), number))
        for filename in ["csv/conditions.csv", "csv/allergies.csv"]:
            with archive.open(filename) as handle:
                for row in csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig")):
                    text = row.get("DESCRIPTION", "").strip()
                    if text:
                        pools["semantic"].append((text, None))
        with archive.open("csv/medications.csv") as handle:
            medications = [row.get("DESCRIPTION", "").strip() for row in csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig"))]
    medications = [item for item in medications if item]
    pools["complex"] = [(f"concomitant medications: {medications[i]}; {medications[i + 1]}", None) for i in range(0, len(medications) - 1, 2)]
    return pools


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rules = load_rules()
    indicators = load_indicators()
    by_label = {label: [rule for rule in rules if rule["expert_label"] == label] for label in ["ExpertA", "ExpertB", "ExpertC"]}
    group_target = min(100, *(len(rows) for rows in by_label.values()))
    rng = random.Random(20260115)
    rows = []
    for label, candidates in by_label.items():
        selected = rng.sample(candidates, group_target)
        pool_key = {"ExpertA": "numeric", "ExpertB": "semantic", "ExpertC": "complex"}[label]
        pool = indicators[pool_key]
        for rule in selected:
            start = int(rule["group_id"], 16) % len(pool)
            for offset in range(4):
                indicator_text, indicator_value = pool[(start + offset) % len(pool)]
                features = extract_router_features(rule["rule_text"], rule["section"], rule["severity"], indicator_text, indicator_value)
                rows.append({
                    "pair_id": f"PUB-{len(rows) + 1:04d}",
                    **rule,
                    "indicator_text": indicator_text,
                    "indicator_value": "" if indicator_value is None else indicator_value,
                    **dict(zip(FEATURE_NAMES, features)),
                })
    fields = ["pair_id", "group_id", "set_id", "drug", "section", "severity", "expert_label", "rule_text", "indicator_text", "indicator_value", *FEATURE_NAMES]
    with (OUT / "router_pairs_public_policy.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "dataset_name": "Public-label policy-supervised router pairs",
        "pair_count": len(rows),
        "unique_rule_groups": group_target * 3,
        "label_counts": Counter(row["expert_label"] for row in rows),
        "label_provenance": "Deterministic routing policy; no pharmacist annotation",
        "rule_source": "openFDA Drug Label API, 200 records",
        "indicator_source": "Synthea official CSV sample data",
        "seed": 20260115,
        "feature_names": FEATURE_NAMES,
    }
    (OUT / "router_dataset_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False, default=dict))


if __name__ == "__main__":
    main()
