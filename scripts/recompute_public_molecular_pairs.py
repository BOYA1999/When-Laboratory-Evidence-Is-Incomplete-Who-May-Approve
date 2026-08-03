import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prescription_mcp.molecular import MolecularEvidence


INPUT = ROOT / "data" / "molecular" / "pair_provenance_public_60.csv"
OUTPUT_DIR = ROOT / "outputs" / "molecular_public_mcp"
THRESHOLDS = (0.30, 0.35, 0.40, 0.45, 0.50)


def main():
    evidence = MolecularEvidence()
    with INPUT.open(encoding="utf-8-sig", newline="") as handle:
        pairs = list(csv.DictReader(handle))

    results = []
    for pair in pairs:
        comparison = evidence.compare(pair["drug_a"], pair["drug_b"])
        results.append({
            "pair_id": pair["pair_id"],
            "drug_a": pair["drug_a"],
            "drug_b": pair["drug_b"],
            "subset_assignment": pair["subset_assignment"],
            **comparison,
        })

    available = [row for row in results if row["available"]]
    summary = {
        "pair_count": len(results),
        "available_count": len(available),
        "missing_count": len(results) - len(available),
        "source": "PubChem PUG REST cached structures",
        "rdkit_version": available[0]["rdkit_version"] if available else None,
        "threshold_curve": [
            {
                "threshold": threshold,
                "escalated_pairs": sum(row["morgan_tanimoto"] >= threshold for row in available),
                "escalated_proportion": round(
                    sum(row["morgan_tanimoto"] >= threshold for row in available) / len(available), 4
                ) if available else None,
            }
            for threshold in THRESHOLDS
        ],
        "interpretation": "Descriptive policy sensitivity only; no clinical cross-reactivity labels are used.",
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "public_molecular_pair_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "public_molecular_threshold_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
