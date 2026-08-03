from app import sample_payload
from prescription_mcp.orchestrator import PrescriptionReviewOrchestrator


def main() -> None:
    orchestrator = PrescriptionReviewOrchestrator()
    positive = orchestrator.review(sample_payload())
    assert positive["status"] == "review required", positive
    assert positive["coverage_status"] == "validated public domains", positive
    assert positive["matched_alerts"], positive

    unsupported = orchestrator.review({"id": "U1", "medications": [{"drug": "acetaminophen", "dose_mg": 500, "frequency": "bid"}]})
    assert unsupported["status"] == "review required", unsupported
    assert unsupported["coverage_status"] == "unsupported", unsupported

    empty = orchestrator.review({})
    assert empty["status"] == "invalid input", empty

    intact = orchestrator.review({"id": "N1", "medications": [{"drug": "nifedipine GITS", "dose_mg": 30, "frequency": "qd"}]})
    assert intact["status"] == "approved", intact

    altered = orchestrator.review({"id": "N2", "medications": [{"drug": "nifedipine GITS", "dose_mg": 30, "frequency": "qd", "crushed": True}]})
    assert altered["status"] == "review required", altered

    fallback = orchestrator.review(sample_payload(), force_fallback=True)
    assert fallback["fallback_used"] is True, fallback
    print("smoke tests passed")


if __name__ == "__main__":
    main()
