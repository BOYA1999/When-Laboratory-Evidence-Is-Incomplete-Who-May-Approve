from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from prescription_mcp.orchestrator import PrescriptionReviewOrchestrator


orchestrator = PrescriptionReviewOrchestrator()


class ReviewHandler(BaseHTTPRequestHandler):
    server_version = "PrescriptionMCP/1.0"

    def do_GET(self) -> None:
        if self.path in {"/", "/api/health"}:
            self._json({"ok": True, "service": "prescription-mcp-demo"})
        elif self.path == "/api/sample":
            self._json(sample_payload())
        else:
            self._json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/review":
            self._json({"error": "not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except json.JSONDecodeError as exc:
            self._json({"error": "invalid JSON", "detail": str(exc)}, status=400)
            return
        query = parse_qs(parsed.query)
        force_fallback = query.get("force_fallback", ["false"])[0].lower() in {"1", "true", "yes"}
        result = orchestrator.review(payload, force_fallback=force_fallback)
        self._json(result, status=400 if result["status"] == "invalid input" else 200)

    def log_message(self, format: str, *args) -> None:
        return

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def sample_payload() -> dict:
    return {
        "id": "PC001",
        "patient": {
            "id": "P001",
            "age": 75,
            "sex": "M",
            "weight_kg": 65,
            "scr_umol_l": 150,
            "egfr": 35,
            "allergies": [
                {"drug": "penicillin", "reaction": "anaphylactic shock", "severity": "life_threatening"}
            ],
            "diagnoses": ["atrial fibrillation", "CKD G3b"],
        },
        "medications": [
            {"drug": "ceftazidime", "dose_mg": 1000, "frequency": "q8h"},
            {"drug": "warfarin", "dose_mg": 3, "frequency": "qd"},
            {"drug": "ibuprofen", "dose_mg": 400, "frequency": "tid"},
        ],
        "review_targets": ["ceftazidime", "warfarin"],
    }


def main() -> None:
    host = "127.0.0.1"
    port = 8000
    server = ThreadingHTTPServer((host, port), ReviewHandler)
    print(f"Prescription review HTTP compatibility API running at http://{host}:{port}")
    print("Health: /api/health  Sample: /api/sample  Review: POST /api/review")
    server.serve_forever()


if __name__ == "__main__":
    main()
