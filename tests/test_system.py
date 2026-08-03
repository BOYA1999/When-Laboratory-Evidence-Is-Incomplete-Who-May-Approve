from app import sample_payload
from prescription_mcp.orchestrator import PrescriptionReviewOrchestrator
from dataclasses import replace


def test_fail_closed_for_unsupported_and_empty_inputs() -> None:
    orchestrator = PrescriptionReviewOrchestrator()
    unsupported = orchestrator.review({"medications": [{"drug": "amoxicillin", "dose_mg": 500, "frequency": "tid"}]})
    assert unsupported["status"] == "review required"
    assert unsupported["coverage_status"] == "unsupported"
    assert orchestrator.review({})["status"] == "invalid input"


def test_sentinel_review_and_provenance() -> None:
    result = PrescriptionReviewOrchestrator().review(sample_payload())
    assert result["status"] == "review required"
    assert result["coverage_status"] == "validated public domains"
    assert result["matched_alerts"][0]["provenance"]["set_id"]


def test_formulation_constraint() -> None:
    orchestrator = PrescriptionReviewOrchestrator()
    intact = {"medications": [{"drug": "nifedipine GITS", "dose_mg": 30, "frequency": "qd"}]}
    altered = {"medications": [{"drug": "nifedipine GITS", "dose_mg": 30, "frequency": "qd", "administration": "tablet crushed"}]}
    assert orchestrator.review(intact)["status"] == "approved"
    assert orchestrator.review(altered)["status"] == "review required"


def test_extended_public_domains() -> None:
    orchestrator = PrescriptionReviewOrchestrator()
    assert len(orchestrator.registry.domains) == 19

    metformin = {
        "patient": {"egfr": 24, "crcl": 80},
        "review_targets": ["metformin"],
        "medications": [{"drug": "metformin", "dose_mg": 500, "frequency": "bid"}],
    }
    sildenafil = {
        "review_targets": ["sildenafil"],
        "medications": [
            {"drug": "sildenafil", "dose_mg": 50, "frequency": "prn"},
            {"drug": "nitroglycerin", "dose_mg": 0.4, "frequency": "prn"},
        ],
    }
    bupropion = {
        "review_targets": ["bupropion xl"],
        "medications": [{"drug": "bupropion xl", "dose_mg": 150, "frequency": "qd", "administration": "tablet crushed"}],
    }
    assert orchestrator.review(metformin, force_fallback=True)["status"] == "rejected"
    assert orchestrator.review(sildenafil, force_fallback=True)["status"] == "rejected"
    assert orchestrator.review(bupropion, force_fallback=True)["status"] == "review required"

    enoxaparin = {
        "patient": {"egfr": 80, "crcl": 24},
        "review_targets": ["enoxaparin"],
        "medications": [{"drug": "enoxaparin", "dose_mg": 40, "frequency": "qd"}],
    }
    assert orchestrator.review(enoxaparin, force_fallback=True)["status"] == "review required"


def test_router_and_rdkit_are_runtime_components() -> None:
    orchestrator = PrescriptionReviewOrchestrator()
    result = orchestrator.review(sample_payload())
    assert result["routing"]
    assert abs(sum(result["routing"][0]["probabilities"].values()) - 1.0) < 1e-6
    molecular = result["molecular_results"][0]
    assert molecular["available"] is True
    assert molecular["rdkit_version"]
    assert 0.0 <= molecular["morgan_tanimoto"] <= 1.0


def test_fail_closed_on_unit_retrieval_conflict_and_service_faults() -> None:
    payload = sample_payload()
    payload["medications"][0]["dose_unit"] = "g"
    assert PrescriptionReviewOrchestrator().review(payload)["status"] == "review required"

    missing = PrescriptionReviewOrchestrator()
    missing.kb.retrieve_rules = lambda *_: []
    assert missing.review(sample_payload())["status"] == "review required"

    conflict = PrescriptionReviewOrchestrator()
    original = conflict.kb.retrieve_rules
    conflict.kb.retrieve_rules = lambda *args: (lambda rules: rules + [replace(rules[0], id=rules[0].id + "-CONFLICT", action_text="No pharmacist review is required.")])(original(*args))
    assert "conflicting normalized label rules detected" in conflict.review(sample_payload())["coverage_issues"]

    failed = PrescriptionReviewOrchestrator()
    failed.kb.retrieve_rules = lambda *_: (_ for _ in ()).throw(RuntimeError("injected"))
    result = failed.review(sample_payload())
    assert result["coverage_status"] == "service failure"
    assert result["status"] == "review required"


def test_lab_evidence_threshold_and_validity_gate() -> None:
    payload = {
        "patient": {
            "encounter_id": "ENC-1",
            "review_time": "2026-07-28T08:00:00Z",
            "labs": [{
                "name": "potassium", "value": 4.4, "unit": "mEq/L",
                "collected_at": "2026-07-27T08:00:00Z", "encounter_id": "ENC-1",
            }],
        },
        "review_targets": ["spironolactone"],
        "medications": [{"drug": "spironolactone", "dose_mg": 25, "frequency": "qd"}],
    }
    assert PrescriptionReviewOrchestrator().review(payload, force_fallback=True)["status"] == "approved"

    payload["patient"]["labs"][0]["value"] = 5.4
    assert PrescriptionReviewOrchestrator().review(payload, force_fallback=True)["status"] == "review required"

    payload["patient"]["labs"][0]["value"] = 4.4
    payload["patient"]["labs"][0]["encounter_id"] = "ENC-OTHER"
    result = PrescriptionReviewOrchestrator().review(payload, force_fallback=True)
    assert result["status"] == "review required"
    assert "belongs to another encounter" in result["coverage_issues"][0]


def test_lab_review_context_exposes_evidence_without_decision() -> None:
    payload = {
        "id": "CONTEXT-1",
        "patient": {
            "encounter_id": "ENC-1",
            "review_time": "2026-07-28T08:00:00Z",
            "labs": [{
                "name": "potassium", "value": 4.4, "unit": "mEq/L",
                "collected_at": "2026-07-27T08:00:00Z", "encounter_id": "ENC-1",
            }],
        },
        "review_targets": ["spironolactone"],
        "medications": [{"drug": "spironolactone", "dose_mg": 25, "frequency": "qd"}],
    }
    context = PrescriptionReviewOrchestrator().lab_review_context(payload)
    assert context["laboratory_evidence"][0]["value"] == 4.4
    assert context["rules"][0]["threshold"] == 5.0
    assert "status" not in context
