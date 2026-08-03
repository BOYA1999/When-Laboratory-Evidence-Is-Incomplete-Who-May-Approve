from __future__ import annotations

import argparse
import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from prescription_mcp.calc import CalcMCPServer
from prescription_mcp.orchestrator import PrescriptionReviewOrchestrator


orchestrator = PrescriptionReviewOrchestrator()
calculator = CalcMCPServer()
mcp = FastMCP(
    "Auditable Prescription Review",
    instructions="Pharmacist-facing research service. Unvalidated drug domains fail closed and require pharmacist review.",
    json_response=True,
    host="127.0.0.1",
    port=8001,
)


@mcp.tool()
def review_prescription(payload: dict[str, Any], force_fallback: bool = False) -> dict[str, Any]:
    """Review a prescription within validated drug domains and return provenance-linked evidence."""
    return orchestrator.review(payload, force_fallback=force_fallback)


@mcp.tool()
def get_lab_review_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Return normalized laboratory evidence, validity notices, and sourced rules without a final decision."""
    return orchestrator.lab_review_context(payload)


@mcp.tool()
def calculate_egfr(age: int, sex: str, scr_umol_l: float) -> dict[str, Any]:
    """Calculate CKD-EPI 2021 eGFR with explicit units."""
    return calculator.calculate_egfr(age, sex, scr_umol_l)


@mcp.tool()
def calculate_crcl(age: int, sex: str, scr_umol_l: float, weight_kg: float) -> dict[str, Any]:
    """Calculate Cockcroft-Gault creatinine clearance with explicit units."""
    return calculator.calculate_crcl(age, sex, scr_umol_l, weight_kg)


@mcp.tool()
def retrieve_rules(drug: str) -> dict[str, Any]:
    """Return the validated domain and provenance-linked normalized rules for one drug."""
    return orchestrator.registry.describe(drug)


@mcp.tool()
def analyze_molecular_similarity(target_drug: str, reference_drug: str) -> dict[str, Any]:
    """Compute RDKit Morgan, MACCS, and ETKDG shape similarity from public PubChem structures."""
    return orchestrator.kb.molecular.compare(target_drug, reference_drug)


@mcp.resource("drug-domain://{drug}")
def drug_domain_resource(drug: str) -> str:
    """Read the onboarding status, label provenance, and rules for a drug domain."""
    return json.dumps(orchestrator.registry.describe(drug), ensure_ascii=False, indent=2)


@mcp.resource("router://metrics")
def router_metrics_resource() -> str:
    """Read public policy-supervised router metrics and their evidence boundary."""
    return json.dumps(orchestrator.router.metrics, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
