# Executable Authority Boundary for MCP-Integrated Prescription Review

This repository is the public, anonymous reproducibility package for a synthetic study of auxiliary prescription review with laboratory evidence. It evaluates one narrow question:

> When required laboratory evidence is incomplete or discordant, can an executable authority contract prevent a language-model candidate from issuing an unsupported approval?

The contribution is the allocation of final approval authority at the Model Context Protocol (MCP) policy boundary. MCP connectivity, deterministic medication rules, language-model guardrails, and their combination are not claimed as firsts.

## Research status

- Research prototype only. Do not use it for clinical care or autonomous prescription approval.
- All 660 current benchmark cases are synthetic.
- Reference labels and deterministic rules share the same public-label contract. Their agreement is implementation consistency, not clinical accuracy.
- No patient records, author metadata, ethics documents, credentials, API keys, or model weights are included.

## Included evidence

- 528 main scenarios and 132 silent plausible-substitution scenarios across 11 drug-laboratory domains.
- Qwen2.5-3B-Instruct, SmolLM2-1.7B-Instruct, and Phi-3.5-mini-instruct frozen candidate scores.
- Deterministic rules, evidence access, confidence abstention, and governed decision paths.
- A real MCP stdio client compared with a same-evidence direct interface.
- Domain-bootstrap summaries, per-domain confusion counts, threshold sensitivity, repeat and batch-size stability.
- Publication figures in PNG and PDF.
- Public-source router and RDKit molecular-similarity components as ancillary engineering channels.

The deterministic baseline was the strongest comparator inside the shared synthetic contract. The current evidence does not establish residual model value beyond rules. Silent plausible substitution remains an exposed failure boundary.

## Quick start

Python 3.11 or 3.12 is recommended.

```powershell
python -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install --upgrade pip
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
& '.\.venv\Scripts\python.exe' -m pytest -q tests
& '.\.venv\Scripts\python.exe' tests_smoke.py
```

Start the MCP stdio server:

```powershell
& '.\.venv\Scripts\python.exe' mcp_server.py --transport stdio
```

Start the local HTTP research interface:

```powershell
.\start_http.ps1
```

Neither interface is hardened for deployment with protected health information.

## Reproducing the reported study

The supplied `outputs/lab_evidence_benchmark_v2` directory contains the immutable reported scores and summaries. Verify or regenerate figures without downloading model weights:

```powershell
& '.\.venv\Scripts\python.exe' scripts\plot_lab_evidence_study.py
```

A full model rerun requires separate acceptance of each model license, sufficient GPU memory, and a PyTorch build appropriate for the local CUDA environment. Model identifiers and license boundaries are documented in `MODEL_SOURCES.md`. The original run contract records model IDs but not immutable Hugging Face commit revisions, which limits exact future weight-level reproduction.

Run the full benchmark into a new output directory. Do not overwrite the reported outputs:

```powershell
$out = 'outputs/reproduction_lab_evidence_v2'
$python = '.\.venv\Scripts\python.exe'

& $python scripts\run_lab_evidence_benchmark.py --phase prepare --output $out

foreach ($model in @('qwen2.5-3b', 'smollm2-1.7b', 'phi3.5-mini')) {
    foreach ($stage in @('main', 'batch8_repeat1', 'batch8_repeat2', 'batch1_repeat0', 'finalize')) {
        & $python scripts\run_lab_evidence_benchmark.py --phase model --model $model --model-stage $stage --output $out
    }
}

& $python scripts\run_lab_evidence_benchmark.py --phase summarize --output $out
```

## Repository layout

| Path | Purpose |
| --- | --- |
| `prescription_mcp/` | Evidence normalization, deterministic contract, router, molecular tools, and orchestration |
| `mcp_server.py` | MCP server and client-facing tools |
| `scripts/` | Public data retrieval, router training, benchmark execution, and figure generation |
| `data/public/` | Archived public-source inputs and derived router data |
| `data/molecular/` | Public PubChem pair provenance |
| `outputs/lab_evidence_benchmark_v2/` | Frozen synthetic cases, model scores, decisions, and statistics |
| `outputs/lab_evidence_figures_v2/` | Reproducible figures |
| `tests/` | System and real MCP protocol tests |

`MANIFEST_SHA256.csv` records the size and SHA-256 digest of every packaged file except the manifest itself.

## Related open-source projects

These projects are relevant to the study. Only the first three are direct foundations or dependencies of this repository; the others are independent neighboring implementations and were not used to generate the reported results.

| Project | Relevance | Relationship |
| --- | --- | --- |
| [Model Context Protocol Python SDK](https://github.com/modelcontextprotocol/python-sdk) | Official Python client and server SDK | Direct dependency; MIT |
| [Synthea](https://github.com/synthetichealth/synthea) | Synthetic patient and FHIR/CSV data generation | Public data source; Apache-2.0 |
| [RDKit](https://github.com/rdkit/rdkit) | Molecular parsing and Morgan/MACCS fingerprints | Direct dependency; BSD-3-Clause |
| [health-record-mcp](https://github.com/jmandel/health-record-mcp) | SMART on FHIR access exposed through MCP | Related independent project; MIT |
| [OMOP MCP](https://github.com/OHNLP/omop_mcp) | MCP-based clinical terminology mapping to OMOP concepts | Related independent project; Apache-2.0 |
| [FHIR Server for Azure](https://github.com/microsoft/fhir-server) | Open-source FHIR service and interoperability backend | Related infrastructure; MIT |

Listing a project does not imply endorsement, collaboration, code reuse, or experimental dependence beyond the relationship stated above.

## License and third-party material

Repository-authored code is released under the MIT License. Third-party data, software, and models retain their own terms. See `DATA_SOURCES.md`, `MODEL_SOURCES.md`, and `THIRD_PARTY_NOTICES.md` before redistribution or commercial use.

In particular, `Qwen/Qwen2.5-3B-Instruct` is governed by the Qwen Research License and is restricted to non-commercial purposes unless a separate license is obtained. Model weights are not included in this repository.
