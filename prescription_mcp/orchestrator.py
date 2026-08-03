from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from .calc import CalcMCPServer, is_number
from .emr import EMRMCPServer
from .kb import KBMCPServer
from .models import Indicator, MatchResult, Medication, Prescription, Rule, SEVERITY_RANK
from .registry import DrugDomainRegistry, normalize_context_drug
from .router import TrainedRouter


class PrescriptionReviewOrchestrator:
    def __init__(self) -> None:
        self.emr = EMRMCPServer()
        self.calc = CalcMCPServer()
        self.registry = DrugDomainRegistry()
        self.kb = KBMCPServer(self.registry)
        self.router = TrainedRouter()

    def review(self, payload: dict[str, Any], force_fallback: bool = False) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            return self._review(payload, force_fallback, started)
        except Exception as exc:
            prescription_id = str(payload.get("id", "unknown")) if isinstance(payload, dict) else "unknown"
            return self._blocked(
                prescription_id,
                "service failure",
                [f"MCP service failure: {type(exc).__name__}"],
                started,
            )

    def lab_review_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        prescription = self.emr.build_prescription(payload)
        targets, context, issues = self._resolve_targets(prescription)
        issues = _input_issues(payload) + issues
        normalized = replace(prescription, medications=targets + context)
        target_names = [medication.drug for medication in targets]
        indicators = self._construct_indicators(normalized, [], target_names)
        rules = self.kb.retrieve_rules(target_names, indicators)
        if not rules:
            issues.append("no label rules retrieved for a validated target")
        issues.extend(_rule_conflict_issues(rules))
        issues.extend(_lab_evidence_issues(normalized, rules, payload))
        return {
            "prescription_id": prescription.id,
            "target_names": target_names,
            "patient_context": {
                "age": normalized.patient.age,
                "sex": normalized.patient.sex,
                "weight_kg": normalized.patient.weight_kg,
                "encounter_id": normalized.patient.encounter_id,
                "review_time": normalized.patient.review_time,
            },
            "medications": [medication.__dict__ for medication in normalized.medications],
            "laboratory_evidence": normalized.patient.labs,
            "data_quality_notices": list(dict.fromkeys(issues)),
            "rules": [
                {
                    "drug": rule.drug,
                    "condition_text": rule.condition_text,
                    "action_text": rule.action_text,
                    "lab_name": rule.lab_name,
                    "lab_unit": rule.lab_unit,
                    "threshold_operator": rule.threshold_operator,
                    "threshold": rule.threshold,
                    "max_age_days": rule.max_age_days,
                    "provenance": rule.provenance,
                }
                for rule in rules
            ],
        }

    def _review(self, payload: dict[str, Any], force_fallback: bool, started: float) -> dict[str, Any]:
        audit: list[dict[str, Any]] = []
        prescription = self.emr.build_prescription(payload)
        if not prescription.medications:
            return self._blocked(prescription.id, "invalid", ["at least one medication is required"], started, status="invalid input")

        targets, context, issues = self._resolve_targets(prescription)
        issues = _input_issues(payload) + issues
        if not targets:
            names = [med.drug for med in prescription.medications]
            return self._blocked(prescription.id, "unsupported", [f"no validated review target among: {', '.join(names)}"], started)
        audit.append(_audit(self.emr.name, "build_prescription", {"id": prescription.id}, f"{len(prescription.medications)} medications"))
        normalized = replace(prescription, medications=targets + context)
        target_names = [med.drug for med in targets]
        indicators = self._construct_indicators(normalized, audit, target_names)
        rules = self.kb.retrieve_rules(target_names, indicators)
        if not rules:
            issues.append("no label rules retrieved for a validated target")
        issues.extend(_rule_conflict_issues(rules))
        issues.extend(_lab_evidence_issues(normalized, rules, payload))
        audit.append(_audit(self.kb.name, "retrieve_rules", {"targets": target_names}, f"{len(rules)} candidate rules"))

        molecular_results = []
        for med in targets:
            molecular_results.extend(self.kb.analyze_molecular_similarity(med.drug, prescription.patient.allergies))
        molecular_alerts = [result for result in molecular_results if result.get("escalate")]
        if molecular_results:
            audit.append(_audit(self.kb.name, "analyze_molecular_similarity", {"comparisons": len(molecular_results)}, f"{len(molecular_alerts)} escalation signals"))

        matches = []
        routing = []
        for rule in rules:
            for indicator in indicators:
                route = self.router.route(rule, indicator)
                routing.append(route)
                result = self._match(rule, indicator, route, force_fallback)
                if route["secondary_expert"]:
                    secondary_route = {**route, "primary_expert": route["secondary_expert"]}
                    secondary = self._match(rule, indicator, secondary_route, force_fallback)
                    if secondary.matched != result.matched:
                        result = MatchResult(**{**result.__dict__, "disagreement": True, "matched": result.matched or secondary.matched})
                matches.append(result)

        conclusion = self._aggregate(matches, molecular_alerts, issues)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "prescription_id": prescription.id,
            "coverage_status": "incomplete" if issues else "validated public domains",
            "coverage_issues": issues,
            "status": conclusion["status"],
            "risk_level": conclusion["risk_level"],
            "summary": conclusion["summary"],
            "matched_alerts": [match.__dict__ for match in matches if match.matched],
            "molecular_results": molecular_results,
            "molecular_alerts": molecular_alerts,
            "indicators": [indicator.__dict__ for indicator in indicators],
            "rules": [rule.__dict__ for rule in rules],
            "routing": routing,
            "audit": audit,
            "latency_ms": elapsed_ms,
            "fallback_used": force_fallback or any(match.fallback_used for match in matches),
        }

    def _resolve_targets(self, prescription: Prescription) -> tuple[list[Medication], list[Medication], list[str]]:
        requested = set()
        unknown_requested = []
        for name in prescription.review_targets:
            domain = self.registry.resolve(name)
            if domain:
                requested.add(domain["canonical_name"])
            else:
                unknown_requested.append(name)
        targets, context, issues = [], [], []
        for medication in prescription.medications:
            domain = self.registry.resolve(medication.drug)
            explicitly_requested = not prescription.review_targets or (domain and domain["canonical_name"] in requested)
            if domain and explicitly_requested:
                normalized = self.registry.normalize_medication(medication)
                assert normalized is not None
                missing = self.registry.validate_medication(normalized)
                if missing:
                    issues.append(f"{medication.drug}: missing {', '.join(missing)}")
                targets.append(normalized)
            else:
                context.append(medication)
        present_targets = {med.drug for med in targets}
        for requested_name in requested - present_targets:
            issues.append(f"requested target is absent: {requested_name}")
        issues.extend(f"requested target is not validated: {name}" for name in unknown_requested)
        return targets, context, issues

    def _construct_indicators(
        self,
        prescription: Prescription,
        audit: list[dict[str, Any]],
        target_names: list[str] | None = None,
    ) -> list[Indicator]:
        patient = prescription.patient
        indicators: list[Indicator] = []
        egfr = patient.egfr
        if egfr is None and patient.age and patient.sex and patient.scr_umol_l:
            result = self.calc.calculate_egfr(patient.age, patient.sex, patient.scr_umol_l)
            egfr = result["egfr"]
            audit.append(_audit(self.calc.name, "calculate_egfr", {"patient_id": patient.id}, result))
        if egfr is not None and egfr < 60:
            indicators.append(Indicator("eGFR", egfr, "renal_function", "moderate" if egfr >= 30 else "high", "calc", ("egfr", "renal", "creatinine", "dose")))

        crcl = patient.crcl
        if crcl is None and patient.age and patient.sex and patient.scr_umol_l and patient.weight_kg:
            result = self.calc.calculate_crcl(patient.age, patient.sex, patient.scr_umol_l, patient.weight_kg)
            crcl = result["crcl"]
            audit.append(_audit(self.calc.name, "calculate_crcl", {"patient_id": patient.id}, result))
        if crcl is not None and crcl < 60:
            indicators.append(Indicator("CrCl", crcl, "renal_function", "moderate" if crcl >= 30 else "high", "calc", ("crcl", "renal", "creatinine", "dose")))

        for raw in patient.labs:
            if not isinstance(raw, dict) or not raw.get("name"):
                continue
            name = _normalize_lab_name(str(raw["name"]))
            value = raw.get("value", raw.get("status"))
            status = str(raw.get("status", "")).lower()
            keywords = tuple(dict.fromkeys((name, status, "laboratory")))
            indicators.append(Indicator(name, value, "laboratory", "moderate" if status == "abnormal" else "low", "emr", keywords))

        for allergy in patient.allergies:
            severity = _normalize_severity(str(allergy.get("severity", "moderate")).lower())
            drug = normalize_context_drug(str(allergy.get("drug", "unknown")))
            reaction = str(allergy.get("reaction", ""))
            terms = (drug, "anaphylaxis" if "anaphyl" in reaction.lower() else "")
            indicators.append(Indicator(f"allergy:{drug}", {"drug": drug, "reaction": reaction}, "allergy", severity, "emr", tuple(term for term in terms if term)))

        medication_names = {normalize_context_drug(med.drug) for med in prescription.medications}
        names = target_names or [med.drug for med in prescription.medications if self.registry.resolve(med.drug)]
        target_rules = self.registry.rules_for(names)
        for rule in target_rules:
            required = {term.removeprefix("drug:") for term in rule.keywords if term.startswith("drug:")}
            if rule.rule_type == "interaction" and required and required.issubset(medication_names):
                indicators.append(Indicator(
                    f"co-medication:{'+'.join(sorted(required))}",
                    " + ".join(sorted(required)),
                    "interaction",
                    rule.severity,
                    "emr",
                    rule.keywords,
                ))
        for medication in prescription.medications:
            if medication.drug not in names:
                continue
            administration = (medication.administration or "").lower()
            normalized_terms = tuple(
                normalized
                for source, normalized in (
                    ("crush", "crushed"),
                    ("chew", "chewed"),
                    ("bitten", "bitten"),
                    ("divid", "divided"),
                    ("split", "split"),
                    ("cut", "divided"),
                )
                if source in administration
            )
            if normalized_terms:
                indicators.append(Indicator(
                    f"formulation:altered:{medication.drug}",
                    administration,
                    "formulation",
                    "high",
                    "emr",
                    normalized_terms,
                ))

        if not indicators:
            indicators.append(Indicator("no_abnormal_indicator", "none", "none", "low", "emr", ("routine",)))
        return indicators

    def _match(self, rule: Rule, indicator: Indicator, route: dict, force_fallback: bool) -> MatchResult:
        expert = route["primary_expert"]
        if force_fallback or expert == "ExpertA" or rule.high_risk:
            matched, reason = self._deterministic_match(rule, indicator)
            expert_name = "DeterministicFallback" if force_fallback else expert
        else:
            matched, reason = self._constrained_semantic_match(rule, indicator)
            expert_name = expert
        return MatchResult(
            rule_id=rule.id,
            indicator_name=indicator.name,
            matched=matched,
            expert=expert_name,
            confidence=route["top1_probability"],
            reason=reason,
            severity=rule.severity,
            action=rule.action_text,
            provenance=rule.provenance,
            fallback_used=force_fallback,
        )

    @staticmethod
    def _deterministic_match(rule: Rule, indicator: Indicator) -> tuple[bool, str]:
        if rule.rule_type == "numeric" and indicator.kind in {"renal_function", "laboratory"} and is_number(indicator.value) and rule.threshold is not None:
            metric = indicator.name.lower()
            if rule.lab_name and _normalize_lab_name(metric) != _normalize_lab_name(rule.lab_name):
                return False, "rule does not own this laboratory indicator"
            if metric == "egfr" and "egfr" not in rule.keywords:
                return False, "rule does not own the eGFR indicator"
            if metric == "crcl" and "crcl" not in rule.keywords:
                return False, "rule does not own the CrCl indicator"
            matched = _compare(float(indicator.value), rule.threshold_operator, rule.threshold)
            return matched, f"{indicator.name}={indicator.value}; threshold {rule.threshold_operator}{rule.threshold}"
        if rule.rule_type == "monitoring" and indicator.kind == "laboratory" and rule.lab_name:
            owned = _normalize_lab_name(indicator.name) == _normalize_lab_name(rule.lab_name)
            abnormal = str(indicator.value).lower() in {"abnormal", "positive", "critical"} or "abnormal" in indicator.keywords
            return owned and abnormal, "required laboratory panel is abnormal" if owned and abnormal else "monitoring evidence present without an abnormal flag"
        if rule.rule_type == "interaction":
            required = {term for term in rule.keywords if term.startswith("drug:")}
            matched = required.issubset(set(indicator.keywords)) and indicator.kind == "interaction"
            return matched, "required co-medications present" if matched else "interaction pair absent"
        if rule.rule_type == "allergy":
            matched = indicator.kind == "allergy" and bool(set(rule.keywords).intersection(indicator.keywords))
            return matched, "allergen or reaction phenotype matched" if matched else "allergy evidence absent"
        if rule.rule_type == "formulation":
            matched = indicator.kind == "formulation" and bool(set(rule.keywords).intersection(indicator.keywords))
            return matched, "extended-release administration constraint violated" if matched else "formulation violation absent"
        return False, "rule requires bounded semantic matching"

    @staticmethod
    def _constrained_semantic_match(rule: Rule, indicator: Indicator) -> tuple[bool, str]:
        shared = set(rule.keywords).intersection(indicator.keywords)
        if shared and indicator.kind != "none":
            return True, f"supplied rule and indicator share {sorted(shared)}"
        return False, "no applicability match from supplied evidence"

    @staticmethod
    def _aggregate(matches: list[MatchResult], molecular_alerts: list[dict], coverage_issues: list[str]) -> dict[str, str]:
        matched = [item for item in matches if item.matched]
        severity = "high" if molecular_alerts else max((item.severity for item in matched), key=lambda value: SEVERITY_RANK.get(value, 0), default="low")
        if severity == "critical":
            status, risk = "rejected", "critical"
        elif severity in {"high", "moderate"} or coverage_issues:
            status, risk = "review required", "high" if severity == "high" or coverage_issues else "medium"
        else:
            status, risk = "approved", "low"
        summary_parts = list(dict.fromkeys(item.action for item in matched))[:3]
        if molecular_alerts:
            summary_parts.append("molecular similarity threshold met; pharmacist review required")
        if coverage_issues:
            summary_parts.append("coverage incomplete: " + "; ".join(coverage_issues))
        return {"status": status, "risk_level": risk, "summary": "; ".join(summary_parts) or "No applicable validated-domain rule matched."}

    @staticmethod
    def _blocked(prescription_id: str, coverage_status: str, issues: list[str], started: float, status: str = "review required") -> dict[str, Any]:
        return {
            "prescription_id": prescription_id,
            "coverage_status": coverage_status,
            "coverage_issues": issues,
            "status": status,
            "risk_level": "undetermined",
            "summary": "; ".join(issues),
            "matched_alerts": [],
            "molecular_results": [],
            "molecular_alerts": [],
            "rules": [],
            "routing": [],
            "audit": [],
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "fallback_used": True,
        }


def _audit(server: str, operation: str, params: dict[str, Any], result_summary: Any) -> dict[str, Any]:
    return {"server": server, "operation": operation, "params": params, "result_summary": result_summary, "timestamp_ms": int(time.time() * 1000)}


def _normalize_severity(value: str) -> str:
    if value in {"critical", "contraindicated"}:
        return "critical"
    if value in {"life_threatening", "life-threatening", "anaphylaxis", "severe", "high"}:
        return "high"
    if value in {"moderate", "medium"}:
        return "moderate"
    return "low"


def _input_issues(payload: dict[str, Any]) -> list[str]:
    patient = payload.get("patient", {}) if isinstance(payload.get("patient", {}), dict) else {}
    issues = []
    scr_unit = str(patient.get("scr_unit", payload.get("scr_unit", ""))).lower().replace(" ", "")
    if scr_unit and scr_unit not in {"umol/l", "µmol/l", "μmol/l"}:
        issues.append(f"unexpected serum-creatinine unit: {scr_unit}")
    medications = payload.get("medications") or payload.get("drugs") or []
    for item in medications:
        if not isinstance(item, dict):
            continue
        unit = str(item.get("dose_unit", "mg")).lower().strip()
        if unit != "mg":
            issues.append(f"{item.get('drug', item.get('name', 'medication'))}: unexpected dose unit {unit}")
    return issues


def _rule_conflict_issues(rules: list[Rule]) -> list[str]:
    actions: dict[tuple[str, str, str], set[str]] = {}
    for rule in rules:
        key = (rule.drug, rule.rule_type, " ".join(rule.condition_text.lower().split()))
        actions.setdefault(key, set()).add(" ".join(rule.action_text.lower().split()))
    return ["conflicting normalized label rules detected" for values in actions.values() if len(values) > 1]


def _normalize_lab_name(value: str) -> str:
    compact = "".join(character for character in value.lower() if character.isalnum())
    aliases = {
        "glomerularfiltrationrate": "egfr",
        "gfr": "egfr",
        "creatinineclearance": "crcl",
        "serumpotassium": "potassium",
        "k": "potassium",
        "absoluteneutrophilcount": "anc",
        "plateletcount": "platelets",
        "serumlithium": "lithium",
        "completebloodcount": "cbc",
        "liverfunctiontests": "lft",
        "liverfunctionpanel": "lft",
    }
    return aliases.get(compact, compact)


def _normalize_unit(value: str) -> str:
    return value.lower().replace(" ", "").replace("μ", "u").replace("µ", "u").replace("²", "2")


def _compare(value: float, operator: str | None, threshold: float) -> bool:
    return {
        "<": value < threshold,
        "<=": value <= threshold,
        ">": value > threshold,
        ">=": value >= threshold,
    }.get(operator or "", False)


def _lab_evidence_issues(prescription: Prescription, rules: list[Rule], payload: dict[str, Any]) -> list[str]:
    patient = prescription.patient
    issues: list[str] = []
    if str(payload.get("lab_service_status", "available")).lower() != "available":
        issues.append("laboratory MCP service unavailable")
    observations = [item for item in patient.labs if isinstance(item, dict) and item.get("name")]
    for rule in rules:
        if not rule.lab_name:
            continue
        name = _normalize_lab_name(rule.lab_name)
        matching = [item for item in observations if _normalize_lab_name(str(item.get("name", ""))) == name]
        legacy_value = patient.egfr if name == "egfr" else patient.crcl if name == "crcl" else None
        if not matching and legacy_value is None:
            issues.append(f"{rule.drug}: missing required laboratory evidence {rule.lab_name}")
            continue
        if not matching:
            continue
        if rule.lab_unit:
            expected = _normalize_unit(rule.lab_unit)
            for item in matching:
                actual = _normalize_unit(str(item.get("unit", "")))
                if actual != expected:
                    issues.append(f"{rule.drug}: unexpected {rule.lab_name} unit {item.get('unit', '') or 'missing'}")
        if patient.encounter_id:
            for item in matching:
                if item.get("encounter_id") and str(item["encounter_id"]) != patient.encounter_id:
                    issues.append(f"{rule.drug}: {rule.lab_name} belongs to another encounter")
        if rule.max_age_days is not None and patient.review_time:
            review_time = _parse_time(patient.review_time)
            for item in matching:
                collected = _parse_time(str(item.get("collected_at", "")))
                if collected is None:
                    issues.append(f"{rule.drug}: {rule.lab_name} timestamp is missing or invalid")
                elif review_time and (review_time - collected).total_seconds() > rule.max_age_days * 86400:
                    issues.append(f"{rule.drug}: {rule.lab_name} is stale")
        values = [float(item["value"]) for item in matching if is_number(item.get("value"))]
        if rule.threshold is not None and len(values) > 1:
            sides = {_compare(value, rule.threshold_operator, rule.threshold) for value in values}
            if len(sides) > 1:
                issues.append(f"{rule.drug}: conflicting {rule.lab_name} results cross the decision threshold")
        statuses = {str(item.get("status", "")).lower() for item in matching if item.get("status")}
        if "normal" in statuses and "abnormal" in statuses:
            issues.append(f"{rule.drug}: conflicting {rule.lab_name} status flags")
    return list(dict.fromkeys(issues))


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
