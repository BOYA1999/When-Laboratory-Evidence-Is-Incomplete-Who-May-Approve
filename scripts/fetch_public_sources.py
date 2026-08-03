from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "public" / "raw"
SOURCES = {
    "synthea_sample_data_csv_apr2020.zip": "https://raw.githubusercontent.com/synthetichealth/synthea-sample-data/main/downloads/synthea_sample_data_csv_apr2020.zip",
}


def download(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "PrescriptionMCPResearch/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, path.open("wb") as handle:
        handle.write(response.read())


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "PrescriptionMCPResearch/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        download(url, RAW / name)
    requests = [f"https://api.fda.gov/drug/label.json?limit=100&skip={skip}" for skip in [0, 100]]
    results = []
    for url in requests:
        results.extend(fetch_json(url)["results"])
    (RAW / "openfda_labels_200.json").write_text(json.dumps({"source": "openFDA Drug Label API", "requests": requests, "results": results}, ensure_ascii=False), encoding="utf-8")
    sentinel_requests = []
    labels = []
    for drug in ["ceftazidime", "nifedipine", "warfarin sodium"]:
        query = urllib.parse.quote(f'openfda.generic_name:"{drug}"')
        url = f"https://api.fda.gov/drug/label.json?search={query}&limit=1"
        sentinel_requests.append(url)
        labels.append({"drug": drug, "request": url, "result": fetch_json(url)["results"][0]})
    (RAW / "sentinel_openfda_labels.json").write_text(json.dumps({"source": "openFDA Drug Label API", "labels": labels}, ensure_ascii=False), encoding="utf-8")
    files = {}
    for path in sorted(RAW.iterdir()):
        if path.is_file():
            files[path.name] = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "files": files, "source_urls": {**SOURCES, "openfda_pages": requests, "openfda_sentinel": sentinel_requests}}
    (ROOT / "data" / "public" / "source_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
