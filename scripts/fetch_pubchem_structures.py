from __future__ import annotations

import csv
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "molecular" / "pair_provenance_public_60.csv"
OUTPUT = ROOT / "prescription_mcp" / "data" / "public_structures.json"


def main() -> None:
    names_by_cid: dict[int, set[str]] = {}
    with SOURCE.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            for suffix in ["a", "b"]:
                cid = int(row[f"pubchem_cid_{suffix}"])
                names_by_cid.setdefault(cid, set()).add(row[f"drug_{suffix}"])
    cids = sorted(names_by_cid)
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{','.join(map(str, cids))}/property/CanonicalSMILES,IsomericSMILES,InChIKey/JSON"
    request = urllib.request.Request(url, headers={"User-Agent": "PrescriptionMCPResearch/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    structures = {}
    for item in payload["PropertyTable"]["Properties"]:
        cid = int(item["CID"])
        record = {
            "cid": cid,
            "smiles": item.get("SMILES") or item.get("ConnectivitySMILES"),
            "connectivity_smiles": item.get("ConnectivitySMILES"),
            "inchikey": item.get("InChIKey"),
        }
        for name in names_by_cid.get(cid, []):
            structures[name.lower()] = record
    structures["penicillin"] = structures["penicillin g"]
    output = {
        "source": "PubChem PUG REST",
        "source_url": url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "rdkit_input_policy": "PubChem stereochemical SMILES when available",
        "structures": structures,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"structure_count": len(structures), "output": str(OUTPUT)}, indent=2))


if __name__ == "__main__":
    main()
