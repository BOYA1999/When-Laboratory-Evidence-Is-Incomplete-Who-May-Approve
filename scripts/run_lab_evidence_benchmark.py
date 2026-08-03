from __future__ import annotations

import argparse
import asyncio
import csv
import gc
import hashlib
import json
import math
import os
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prescription_mcp.orchestrator import PrescriptionReviewOrchestrator
from scripts.run_public_system_comparison import load_demographics


OUTPUT = ROOT / "outputs/lab_evidence_benchmark_v2"
SEED = 20260728
REVIEW_TIME = datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc)
FAULTS = ("missing", "stale", "unit_error", "conflict", "wrong_encounter", "service_failure")
MODELS = {
    "qwen2.5-3b": "Qwen/Qwen2.5-3B-Instruct",
    "smollm2-1.7b": "HuggingFaceTB/SmolLM2-1.7B-Instruct",
    "phi3.5-mini": "microsoft/Phi-3.5-mini-instruct",
}
DOSES = {
    "ceftazidime": (1000.0, "q8h", "mg"),
    "metformin": (500.0, "bid", "mg"),
    "enoxaparin": (40.0, "qd", "mg"),
    "gabapentin": (300.0, "tid", "mg"),
    "dofetilide": (0.5, "bid", "mg"),
    "spironolactone": (25.0, "qd", "mg"),
    "clozapine": (25.0, "qd", "mg"),
    "heparin": (5000.0, "q8h", "unit"),
    "lithium carbonate": (300.0, "tid", "mg"),
    "linezolid": (600.0, "q12h", "mg"),
    "divalproex sodium": (250.0, "bid", "mg"),
}
CONFIDENCE_THRESHOLD = 0.60
BOOTSTRAP_REPETITIONS = 10000


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_once(path: Path, text: str) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to rewrite frozen output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_csv_once(path: Path, rows: list[dict]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to rewrite frozen output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def p95(values: list[float]) -> float:
    return percentile(values, 0.95)


def lab_rules(orchestrator: PrescriptionReviewOrchestrator) -> dict[str, object]:
    result = {}
    for name in orchestrator.registry.domains:
        rules = [rule for rule in orchestrator.registry.rules_for([name]) if rule.lab_name]
        if len(rules) == 1:
            result[name] = rules[0]
    return result


def threshold_match(rule, value) -> bool:
    if rule.rule_type == "monitoring":
        return value == "abnormal"
    return {
        "<": value < rule.threshold,
        "<=": value <= rule.threshold,
        ">": value > rule.threshold,
        ">=": value >= rule.threshold,
    }[rule.threshold_operator]


def clean_value(rule, risky: bool, index: int, count: int):
    if rule.rule_type == "monitoring":
        return "abnormal" if risky else "normal"
    fraction = (index + 1) / (count + 1)
    threshold = float(rule.threshold)
    if rule.threshold_operator in {"<", "<="}:
        factor = 0.50 + 0.45 * fraction if risky else 1.05 + 0.55 * fraction
    else:
        factor = 1.05 + 0.55 * fraction if risky else 0.40 + 0.55 * fraction
    return round(threshold * factor, 3)


def opposite_value(rule, value, index: int):
    return clean_value(rule, not threshold_match(rule, value), index, 4)


def observation(rule, value, *, age_hours: float, encounter: str, unit: str | None = None) -> dict:
    return {
        "name": rule.lab_name,
        "value": value,
        "status": value if rule.rule_type == "monitoring" else ("abnormal" if threshold_match(rule, value) else "normal"),
        "unit": unit or rule.lab_unit,
        "collected_at": (REVIEW_TIME - timedelta(hours=age_hours)).isoformat(),
        "encounter_id": encounter,
        "source": "synthetic-lis",
    }


def make_payload(case_id: str, domain: str, demographic: dict, labs: list[dict], index: int, service: str = "available") -> dict:
    base_dose, frequency, unit = DOSES[domain]
    dose = round(base_dose * (0.90 + 0.05 * (index % 5)), 3)
    encounter = f"ENC-{1000 + index}"
    return {
        "id": case_id,
        "patient": {
            "id": case_id,
            "age": demographic["age"],
            "sex": demographic["sex"],
            "weight_kg": 50 + (index * 7) % 47,
            "encounter_id": encounter,
            "review_time": REVIEW_TIME.isoformat(),
            "labs": labs,
        },
        "lab_service_status": service,
        "review_targets": [domain],
        "medications": [{"drug": domain, "dose_mg": dose, "frequency": frequency, "dose_unit": unit}],
    }


def build_corpus() -> tuple[list[dict], list[dict]]:
    orchestrator = PrescriptionReviewOrchestrator()
    rules = lab_rules(orchestrator)
    if len(rules) != 11:
        raise RuntimeError(f"Expected 11 laboratory domains, found {len(rules)}")
    demographics = load_demographics()
    random.Random(SEED).shuffle(demographics)
    main, boundary = [], []
    cursor = 0
    for domain_index, (domain, rule) in enumerate(rules.items()):
        for local_index in range(24):
            risky = local_index < 12
            within_class = local_index if risky else local_index - 12
            case_id = f"LAB2-{cursor + 1:04d}"
            encounter = f"ENC-{1000 + cursor}"
            value = clean_value(rule, risky, within_class, 12)
            labs = [observation(rule, value, age_hours=6 + local_index * 2 + domain_index, encounter=encounter)]
            payload = make_payload(case_id, domain, demographics[cursor % len(demographics)], labs, cursor)
            main.append({
                "case_id": case_id,
                "domain": domain,
                "state": "clean",
                "scenario_index": local_index,
                "reference": "review required" if risky else "approved",
                "payload": payload,
            })
            cursor += 1
        for fault_index, fault in enumerate(FAULTS):
            for local_index in range(4):
                case_id = f"LAB2-{cursor + 1:04d}"
                encounter = f"ENC-{1000 + cursor}"
                value = clean_value(rule, local_index < 2, local_index % 2, 2)
                labs = [observation(rule, value, age_hours=8 + local_index * 3 + domain_index, encounter=encounter)]
                service = "available"
                if fault == "missing":
                    labs = []
                elif fault == "stale":
                    labs = [observation(rule, value, age_hours=(rule.max_age_days or 7) * 24 + 24 + local_index * 7, encounter=encounter)]
                elif fault == "unit_error":
                    wrong_units = ["mg/dL", "mmol/L", "g/L", "unknown"]
                    wrong = next(unit for unit in wrong_units[local_index:] + wrong_units[:local_index] if unit != rule.lab_unit)
                    labs = [observation(rule, value, age_hours=9 + local_index * 4, encounter=encounter, unit=wrong)]
                elif fault == "conflict":
                    labs.append(observation(rule, opposite_value(rule, value, local_index), age_hours=7 + local_index, encounter=encounter))
                elif fault == "wrong_encounter":
                    labs = [observation(rule, value, age_hours=10 + local_index * 5, encounter=f"ENC-OTHER-{domain_index}-{local_index}")]
                elif fault == "service_failure":
                    service = ("unavailable", "timeout", "error", "degraded")[local_index]
                payload = make_payload(case_id, domain, demographics[cursor % len(demographics)], labs, cursor, service)
                main.append({
                    "case_id": case_id,
                    "domain": domain,
                    "state": fault,
                    "scenario_index": fault_index * 4 + local_index,
                    "reference": "review required",
                    "payload": payload,
                })
                cursor += 1
        for local_index in range(12):
            case_id = f"LAB2-B-{cursor + 1:04d}"
            hidden = clean_value(rule, True, local_index, 12)
            visible = clean_value(rule, False, local_index, 12)
            encounter = f"ENC-{1000 + cursor}"
            substituted = observation(rule, visible, age_hours=5 + local_index * 2 + domain_index, encounter=encounter)
            substituted.pop("encounter_id")
            payload = make_payload(case_id, domain, demographics[cursor % len(demographics)], [substituted], cursor)
            boundary.append({
                "case_id": case_id,
                "domain": domain,
                "state": "silent_plausible_substitution",
                "scenario_index": local_index,
                "reference": "review required",
                "hidden_trigger_value": hidden,
                "payload": payload,
            })
            cursor += 1
    return main, boundary


def decision_signature(result: dict) -> dict:
    return {
        "status": result["status"],
        "coverage_status": result["coverage_status"],
        "coverage_issues": result["coverage_issues"],
        "matched_rule_ids": sorted(item["rule_id"] for item in result["matched_alerts"]),
    }


def context_prompt(context: dict) -> str:
    rules = [
        {
            "condition": rule["condition_text"],
            "action": rule["action_text"],
            "laboratory": rule["lab_name"],
            "unit": rule["lab_unit"],
            "operator": rule["threshold_operator"],
            "threshold": rule["threshold"],
        }
        for rule in context["rules"]
    ]
    evidence = {
        "patient_context": context["patient_context"],
        "medications": context["medications"],
        "laboratory_evidence": context["laboratory_evidence"],
        "data_quality_notices": context["data_quality_notices"],
    }
    return (
        "Review this synthetic prescription using only the supplied public-label rule and structured evidence. "
        "Return exactly REVIEW_REQUIRED or APPROVED. You retain final decision authority.\n"
        f"Rules: {canonical(rules)}\nEvidence: {canonical(evidence)}"
    )


async def collect_mcp(cases: list[dict]) -> tuple[list[dict], list[dict], list[float], list[float]]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server.py"), "--transport", "stdio"])
    contexts, decisions, context_ms, review_ms = [], [], [], []
    with open(os.devnull, "w") as devnull:
        async with stdio_client(params, errlog=devnull) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                for case in cases:
                    started = time.perf_counter()
                    context_result = await session.call_tool("get_lab_review_context", {"payload": case["payload"]})
                    context_ms.append((time.perf_counter() - started) * 1000)
                    if context_result.isError or not isinstance(context_result.structuredContent, dict):
                        raise RuntimeError(f"MCP context call failed for {case['case_id']}")
                    contexts.append(context_result.structuredContent)
                    started = time.perf_counter()
                    review_result = await session.call_tool("review_prescription", {"payload": case["payload"], "force_fallback": True})
                    review_ms.append((time.perf_counter() - started) * 1000)
                    if review_result.isError or not isinstance(review_result.structuredContent, dict):
                        raise RuntimeError(f"MCP review call failed for {case['case_id']}")
                    decisions.append(review_result.structuredContent)
    return contexts, decisions, context_ms, review_ms


def prepare(output: Path) -> None:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Preparation output already exists: {output}")
    output.mkdir(parents=True, exist_ok=True)
    main, boundary = build_corpus()
    cases = main + boundary
    orchestrator = PrescriptionReviewOrchestrator()
    direct_contexts, direct_decisions, direct_context_ms, direct_review_ms = [], [], [], []
    for case in cases:
        started = time.perf_counter()
        direct_contexts.append(orchestrator.lab_review_context(case["payload"]))
        direct_context_ms.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        direct_decisions.append(orchestrator.review(case["payload"], force_fallback=True))
        direct_review_ms.append((time.perf_counter() - started) * 1000)
    mcp_contexts, mcp_decisions, mcp_context_ms, mcp_review_ms = asyncio.run(collect_mcp(cases))

    prepared = []
    for case, direct_context, mcp_context, direct_decision, mcp_decision in zip(
        cases, direct_contexts, mcp_contexts, direct_decisions, mcp_decisions
    ):
        prompt = context_prompt(mcp_context)
        prepared.append({
            "case_id": case["case_id"],
            "domain": case["domain"],
            "state": case["state"],
            "reference": case["reference"],
            "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "direct_mcp_context_equal": direct_context == mcp_context,
            "direct_mcp_decision_equal": decision_signature(direct_decision) == decision_signature(mcp_decision),
            "deterministic_status": mcp_decision["status"],
            "deterministic_coverage_status": mcp_decision["coverage_status"],
            "deterministic_coverage_issues": mcp_decision["coverage_issues"],
        })
    if len({row["prompt_sha256"] for row in prepared}) != len(prepared):
        raise RuntimeError("The revised corpus still contains duplicate model prompts")
    if not all(row["direct_mcp_context_equal"] and row["direct_mcp_decision_equal"] for row in prepared):
        raise RuntimeError("Direct and MCP interfaces returned different evidence or decisions")

    write_once(output / "synthetic_lab_prescriptions_660.jsonl", "".join(canonical(case) + "\n" for case in cases))
    write_once(output / "prepared_mcp_contexts_660.jsonl", "".join(canonical(row) + "\n" for row in prepared))
    protocol = {
        "cases": len(cases),
        "main_cases": len(main),
        "boundary_cases": len(boundary),
        "domains": 11,
        "main_cases_per_domain": 48,
        "boundary_cases_per_domain": 12,
        "unique_prompt_count": len({row["prompt_sha256"] for row in prepared}),
        "context_equality": sum(row["direct_mcp_context_equal"] for row in prepared) / len(prepared),
        "decision_equality": sum(row["direct_mcp_decision_equal"] for row in prepared) / len(prepared),
        "latency_ms": {
            "direct_context_median": statistics.median(direct_context_ms),
            "direct_context_p95": p95(direct_context_ms),
            "mcp_context_median": statistics.median(mcp_context_ms),
            "mcp_context_p95": p95(mcp_context_ms),
            "direct_review_median": statistics.median(direct_review_ms),
            "direct_review_p95": p95(direct_review_ms),
            "mcp_review_median": statistics.median(mcp_review_ms),
            "mcp_review_p95": p95(mcp_review_ms),
        },
    }
    write_once(output / "protocol_comparison.json", json.dumps(protocol, indent=2, ensure_ascii=False))
    expert = {
        "provenance": "author-provided aggregate confirmation in the 2026-07-28 revision session",
        "reviewers": 5,
        "prior_synthetic_records_reviewed": 1540,
        "system_outputs_visible_during_review": False,
        "consensus_process": "discussion after case review",
        "consensus_labels": "binary pass or fail",
        "aggregate_matches_with_prior_mcp_governed": 1540,
        "aggregate_concordance": 1.0,
        "individual_pre_consensus_labels_retained": False,
        "case_level_consensus_file_retained": False,
        "permitted_analysis": "descriptive blinded consensus concordance only",
        "prohibited_analysis": ["Fleiss kappa", "Gwet AC1", "individual-rater agreement", "case-level expert reanalysis"],
    }
    write_once(output / "pharmacist_consensus_boundary.json", json.dumps(expert, indent=2, ensure_ascii=False))
    contract_files = [
        ROOT / "scripts/run_lab_evidence_benchmark.py",
        ROOT / "prescription_mcp/orchestrator.py",
        ROOT / "prescription_mcp/data/drug_domains_19.json",
        ROOT / "mcp_server.py",
    ]
    contract = {
        "seed": SEED,
        "models": MODELS,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "bootstrap_repetitions": BOOTSTRAP_REPETITIONS,
        "files": {str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path) for path in contract_files},
    }
    write_once(output / "RUN_CONTRACT.json", json.dumps(contract, indent=2, ensure_ascii=False))
    print(json.dumps(protocol, indent=2, ensure_ascii=False))


class FixedChoiceModel:
    def __init__(self, model_id: str) -> None:
        import torch
        import transformers
        from transformers import AutoModelForCausalLM, AutoTokenizer

        random.seed(SEED)
        torch.manual_seed(SEED)
        torch.cuda.manual_seed_all(SEED)
        torch.use_deterministic_algorithms(True, warn_only=True)
        self.torch = torch
        self.transformers_version = transformers.__version__
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, padding_side="left", trust_remote_code=True)
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.tokenizer.truncation_side = "left"
        load_args = {"dtype": torch.bfloat16, "device_map": "cuda", "attn_implementation": "sdpa", "trust_remote_code": True}
        try:
            self.model = AutoModelForCausalLM.from_pretrained(model_id, **load_args).eval()
        except (TypeError, ValueError):
            load_args.pop("attn_implementation")
            self.model = AutoModelForCausalLM.from_pretrained(model_id, **load_args).eval()
        self.model_id = model_id

    def prefix(self, prompt: str) -> str:
        if getattr(self.tokenizer, "chat_template", None):
            return self.tokenizer.apply_chat_template([{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True)
        return f"User: {prompt}\nAssistant:"

    def score(self, prompts: list[str], batch_size: int) -> dict:
        choices = ("REVIEW_REQUIRED", "APPROVED")
        prefixes = [self.prefix(prompt) for prompt in prompts]
        candidates = [(prefix + choice, choice) for prefix in prefixes for choice in choices]
        scores = []
        started = time.perf_counter()
        for start in range(0, len(candidates), batch_size):
            batch = candidates[start:start + batch_size]
            candidate_lengths = []
            for text, choice in batch:
                full_ids = self.tokenizer(text, add_special_tokens=False)["input_ids"]
                prefix_ids = self.tokenizer(text[:-len(choice)], add_special_tokens=False)["input_ids"]
                candidate_lengths.append(len(full_ids) - len(prefix_ids))
            encoded = self.tokenizer(
                [item[0] for item in batch], return_tensors="pt", padding=True, truncation=True,
                max_length=512, add_special_tokens=False,
            ).to(self.model.device)
            with self.torch.inference_mode():
                logits = self.model(**encoded, use_cache=False).logits.float().log_softmax(dim=-1)
            width = encoded["input_ids"].shape[1]
            for row, candidate_length in enumerate(candidate_lengths):
                token_scores = [
                    logits[row, position - 1, encoded["input_ids"][row, position]].item()
                    for position in range(width - candidate_length, width)
                ]
                scores.append(sum(token_scores) / len(token_scores))
        selected, review_probabilities, margins = [], [], []
        for index in range(0, len(scores), 2):
            review_score, approve_score = scores[index:index + 2]
            probability = 1.0 / (1.0 + math.exp(approve_score - review_score))
            selected.append("REVIEW_REQUIRED" if probability >= 0.5 else "APPROVED")
            review_probabilities.append(probability)
            margins.append(abs(review_score - approve_score))
        return {
            "selected": selected,
            "review_probabilities": review_probabilities,
            "margins": margins,
            "seconds": time.perf_counter() - started,
            "batch_size": batch_size,
            "forward_batches": math.ceil(len(candidates) / batch_size),
        }


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def stability_subset(rows: list[dict]) -> list[dict]:
    selected = []
    for domain in sorted({row["domain"] for row in rows}):
        domain_rows = [row for row in rows if row["domain"] == domain]
        selected.extend([row for row in domain_rows if row["state"] == "clean"][:8])
        for state in ("missing", "wrong_encounter", "service_failure", "silent_plausible_substitution"):
            selected.append(next(row for row in domain_rows if row["state"] == state))
    return selected


def score_stage(output: Path, alias: str, stage: str) -> None:
    prepared_path = output / "prepared_mcp_contexts_660.jsonl"
    if not prepared_path.exists():
        raise FileNotFoundError("Run --phase prepare before model evaluation")
    model_dir = output / "models" / alias
    model_dir.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(prepared_path)
    subset = stability_subset(rows)

    if stage != "finalize":
        targets = rows if stage == "main" else subset
        batch_size = 1 if stage == "batch1_repeat0" else 8
        path = model_dir / f"{stage}_scores.json"
        if path.exists():
            raise FileExistsError(f"Frozen score stage already exists: {path}")
        model = FixedChoiceModel(MODELS[alias])
        result = model.score([row["prompt"] for row in targets], batch_size=batch_size)
        result["case_ids"] = [row["case_id"] for row in targets]
        result["model"] = {
            "alias": alias,
            "model_id": MODELS[alias],
            "parameters": model.model.num_parameters(),
            "torch": model.torch.__version__,
            "transformers": model.transformers_version,
            "device": model.torch.cuda.get_device_name(0),
            "dtype": "bfloat16",
        }
        write_once(path, json.dumps(result, indent=2, ensure_ascii=False))
        print(json.dumps({"model": alias, "stage": stage, "cases": len(targets), "seconds": result["seconds"]}, indent=2))
        del model
        gc.collect()
        return

    required = ["main", "batch8_repeat1", "batch8_repeat2", "batch1_repeat0"]
    scores = {}
    for name in required:
        path = model_dir / f"{name}_scores.json"
        if not path.exists():
            raise FileNotFoundError(f"Missing frozen score stage: {path}")
        scores[name] = json.loads(path.read_text(encoding="utf-8"))
    full = scores["main"]
    full_by_id = {
        case_id: (choice, probability, margin)
        for case_id, choice, probability, margin in zip(
            full["case_ids"], full["selected"], full["review_probabilities"], full["margins"]
        )
    }
    stability = {"batch8_repeat0": {row["case_id"]: full_by_id[row["case_id"]] for row in subset}}
    for name in required[1:]:
        result = scores[name]
        stability[name] = {
            case_id: (choice, probability, margin)
            for case_id, choice, probability, margin in zip(
                result["case_ids"], result["selected"], result["review_probabilities"], result["margins"]
            )
        }

    predictions = []
    for row in rows:
        choice, probability, margin = full_by_id[row["case_id"]]
        access_review = choice == "REVIEW_REQUIRED"
        uncertain = max(probability, 1 - probability) < CONFIDENCE_THRESHOLD
        deterministic_review = row["deterministic_status"] != "approved"
        outcomes = {
            "deterministic_rules": deterministic_review,
            "mcp_access_only": access_review,
            "confidence_abstention": access_review or uncertain,
            "mcp_governed": deterministic_review or access_review,
        }
        for method, review in outcomes.items():
            predictions.append({
                "case_id": row["case_id"],
                "domain": row["domain"],
                "state": row["state"],
                "reference": row["reference"],
                "model": alias,
                "method": method,
                "prediction": "review required" if review else "approved",
                "model_choice": choice,
                "review_probability": round(probability, 8),
                "score_margin": round(margin, 8),
                "confidence_abstained": method == "confidence_abstention" and uncertain and not access_review,
                "gate_override": method == "mcp_governed" and deterministic_review and not access_review,
            })
    write_csv_once(model_dir / "predictions.csv", predictions)
    raw = {
        "model": full["model"],
        "main_inference": full,
        "stability": stability,
        "stability_cases": len(subset),
    }
    write_once(model_dir / "raw_scores_and_stability.json", json.dumps(raw, indent=2, ensure_ascii=False))
    print(json.dumps({"model": alias, "stage": "finalize", "predictions": len(predictions)}, indent=2))


def confusion(rows: list[dict]) -> dict:
    tp = sum(row["reference"] == "review required" and row["prediction"] == "review required" for row in rows)
    tn = sum(row["reference"] == "approved" and row["prediction"] == "approved" for row in rows)
    fp = sum(row["reference"] == "approved" and row["prediction"] == "review required" for row in rows)
    fn = sum(row["reference"] == "review required" and row["prediction"] == "approved" for row in rows)
    return {"n": len(rows), "tp": tp, "tn": tn, "fp": fp, "fn": fn}


def metric_value(rows: list[dict], metric: str) -> float | None:
    cm = confusion(rows)
    if metric == "accuracy":
        return (cm["tp"] + cm["tn"]) / cm["n"]
    if metric == "unsafe_approval":
        denominator = cm["tp"] + cm["fn"]
        return cm["fn"] / denominator if denominator else None
    denominator = cm["tn"] + cm["fp"]
    return cm["fp"] / denominator if denominator else None


def domain_bootstrap(rows: list[dict], metric: str) -> list[float]:
    domains = sorted({row["domain"] for row in rows})
    grouped = {domain: [row for row in rows if row["domain"] == domain] for domain in domains}
    rng = random.Random(SEED + sum(map(ord, metric)))
    values = []
    for _ in range(BOOTSTRAP_REPETITIONS):
        sampled = []
        for domain in rng.choices(domains, k=len(domains)):
            sampled.extend(grouped[domain])
        value = metric_value(sampled, metric)
        if value is not None:
            values.append(value)
    return [percentile(values, 0.025), percentile(values, 0.975)]


def metrics(rows: list[dict]) -> dict:
    result = confusion(rows)
    for metric in ("accuracy", "unsafe_approval", "unnecessary_escalation"):
        value = metric_value(rows, metric)
        result[metric] = round(value, 4) if value is not None else None
        result[f"{metric}_domain_bootstrap_95ci"] = [round(value, 4) for value in domain_bootstrap(rows, metric)] if value is not None else None
    return result


def cohen_kappa(first: list[str], second: list[str]) -> float:
    observed = sum(a == b for a, b in zip(first, second)) / len(first)
    first_rate = sum(value == "REVIEW_REQUIRED" for value in first) / len(first)
    second_rate = sum(value == "REVIEW_REQUIRED" for value in second) / len(second)
    expected = first_rate * second_rate + (1 - first_rate) * (1 - second_rate)
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def summarize(output: Path) -> None:
    summary_path = output / "lab_evidence_benchmark_summary.json"
    if summary_path.exists():
        raise FileExistsError(f"Frozen summary already exists: {summary_path}")
    all_rows = []
    stability = {}
    for alias in MODELS:
        prediction_path = output / "models" / alias / "predictions.csv"
        raw_path = output / "models" / alias / "raw_scores_and_stability.json"
        if not prediction_path.exists() or not raw_path.exists():
            raise FileNotFoundError(f"Missing frozen outputs for {alias}")
        with prediction_path.open(encoding="utf-8-sig", newline="") as handle:
            all_rows.extend(csv.DictReader(handle))
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        runs = raw["stability"]
        baseline = runs["batch8_repeat0"]
        stability[alias] = {}
        for name, values in runs.items():
            ids = sorted(baseline)
            first = [baseline[case_id][0] for case_id in ids]
            second = [values[case_id][0] for case_id in ids]
            stability[alias][name] = {
                "n": len(ids),
                "agreement": round(sum(a == b for a, b in zip(first, second)) / len(ids), 4),
                "cohen_kappa": round(cohen_kappa(first, second), 4),
                "max_probability_difference": round(max(abs(baseline[case_id][1] - values[case_id][1]) for case_id in ids), 6),
            }

    overall, domains, faults, boundary, confidence_curves = [], [], [], [], []
    for alias in MODELS:
        model_rows = [row for row in all_rows if row["model"] == alias]
        for method in ("deterministic_rules", "mcp_access_only", "confidence_abstention", "mcp_governed"):
            main_rows = [row for row in model_rows if row["method"] == method and row["state"] != "silent_plausible_substitution"]
            boundary_rows = [row for row in model_rows if row["method"] == method and row["state"] == "silent_plausible_substitution"]
            overall.append({"model": alias, "method": method, **metrics(main_rows)})
            boundary.append({"model": alias, "method": method, **metrics(boundary_rows)})
            for domain in sorted({row["domain"] for row in main_rows}):
                domains.append({"model": alias, "method": method, "domain": domain, **confusion([row for row in main_rows if row["domain"] == domain])})
            for state in FAULTS:
                state_rows = [row for row in main_rows if row["state"] == state]
                faults.append({"model": alias, "method": method, "state": state, **confusion(state_rows), "unsafe_approval": metric_value(state_rows, "unsafe_approval")})

        access = [row for row in model_rows if row["method"] == "mcp_access_only" and row["state"] != "silent_plausible_substitution"]
        for threshold in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75):
            adjusted = []
            for row in access:
                copied = dict(row)
                probability = float(row["review_probability"])
                if row["prediction"] == "approved" and max(probability, 1 - probability) < threshold:
                    copied["prediction"] = "review required"
                adjusted.append(copied)
            confidence_curves.append({"model": alias, "threshold": threshold, **metrics(adjusted)})

    report = {
        "contract": json.loads((output / "RUN_CONTRACT.json").read_text(encoding="utf-8")),
        "protocol": json.loads((output / "protocol_comparison.json").read_text(encoding="utf-8")),
        "pharmacist_consensus_boundary": json.loads((output / "pharmacist_consensus_boundary.json").read_text(encoding="utf-8")),
        "overall": overall,
        "per_domain_confusion": domains,
        "detectable_faults": faults,
        "failure_boundary": boundary,
        "confidence_threshold_curve": confidence_curves,
        "stability": stability,
        "statistical_boundary": "Intervals are percentile bootstrap intervals from 10,000 resamples of the 11 drug domains. They describe domain sensitivity within this synthetic contract and are not clinical confidence intervals.",
    }
    write_once(summary_path, json.dumps(report, indent=2, ensure_ascii=False))
    write_csv_once(output / "overall_metrics.csv", overall)
    write_csv_once(output / "per_domain_confusion.csv", domains)
    write_csv_once(output / "confidence_threshold_curve.csv", confidence_curves)
    print(json.dumps({"overall": overall, "stability": stability}, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("prepare", "model", "summarize"), required=True)
    parser.add_argument("--model", choices=sorted(MODELS))
    parser.add_argument("--model-stage", choices=("main", "batch8_repeat1", "batch8_repeat2", "batch1_repeat0", "finalize"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare(args.output)
    elif args.phase == "model":
        if not args.model or not args.model_stage:
            parser.error("--model and --model-stage are required for --phase model")
        score_stage(args.output, args.model, args.model_stage)
    else:
        summarize(args.output)


if __name__ == "__main__":
    main()
