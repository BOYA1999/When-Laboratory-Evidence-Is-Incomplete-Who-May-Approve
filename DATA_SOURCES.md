# Data Sources and Redistribution Boundary

This public package contains no patient-level clinical records. The benchmark prescriptions, laboratory observations, fault states, prompts, and reference decisions are generated synthetic records.

## Archived public inputs

| Material | Packaged path | Upstream source | Rights and boundary |
| --- | --- | --- | --- |
| Drug labeling records | `data/public/raw/lab_domain_openfda_labels.json`, `openfda_labels_200.json`, `sentinel_openfda_labels.json` | [openFDA Drug Label API](https://open.fda.gov/apis/drug/label/) | Generally public domain and CC0 unless an item is specifically marked otherwise. FDA requests attribution and disclaims clinical use. |
| Synthetic EHR sample | `data/public/raw/synthea_sample_data_csv_apr2020.zip` | [Synthea sample data](https://github.com/synthetichealth/synthea-sample-data) | Synthetic, not patient data. Synthea is distributed under Apache-2.0; retain upstream notices. |
| Compound structures | `prescription_mcp/data/public_structures.json` | [PubChem PUG REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest) | NCBI places no general restriction on molecular database use, but contributor-specific rights and provenance may apply. The packaged file is limited to identifiers and structure strings used by this prototype. |

Retrieval URLs, timestamps, file sizes, and source-file hashes are retained in `data/public/source_manifest.json` where available. The laboratory-label archive also stores query provenance.

## Derived public research data

- `data/public/processed/` contains policy-labeled router examples derived from public openFDA text and Synthea indicators.
- `data/molecular/pair_provenance_public_60.csv` contains public compound identifiers and pair definitions.
- `outputs/lab_evidence_benchmark_v2/synthetic_lab_prescriptions_660.jsonl` contains locally generated synthetic benchmark cases.
- Frozen model scores and decision-path outputs are included for auditability. They are research evidence, not clinical annotations.

The MIT license applies only to repository-authored code and derived materials to the extent the contributors can license them. It does not replace upstream rights, model licenses, database notices, patents, trademarks, or contributor-specific PubChem terms.

## Required cautions

- Do not describe synthetic records as real prescriptions or patient data.
- Do not use openFDA content as a substitute for professional medical advice.
- Do not infer prevalence or hospital performance from the balanced synthetic benchmark.
- Reusers are responsible for checking the current upstream terms before redistribution or commercial use.
