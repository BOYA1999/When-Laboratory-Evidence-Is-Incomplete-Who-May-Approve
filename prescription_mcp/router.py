from __future__ import annotations

from pathlib import Path

import joblib

from .models import Indicator, Rule
from .router_features import extract_router_features


class TrainedRouter:
    def __init__(self, path: Path | None = None, confidence_threshold: float = 0.70) -> None:
        source = path or Path(__file__).with_name("data") / "router_model_public.joblib"
        artifact = joblib.load(source)
        self.model = artifact["model"]
        self.metrics = artifact["metrics"]
        self.confidence_threshold = confidence_threshold

    def route(self, rule: Rule, indicator: Indicator) -> dict:
        indicator_text = f"{indicator.name} {indicator.value}"
        features = extract_router_features(rule.condition_text, rule.section, rule.severity, indicator_text, indicator.value)
        probabilities = self.model.predict_proba([features])[0]
        scores = {label: float(probabilities[index]) for index, label in enumerate(self.model.classes_)}
        ordered = sorted(scores, key=scores.get, reverse=True)
        return {
            "rule_id": rule.id,
            "indicator": indicator.name,
            "feature_family": rule.rule_type,
            "probabilities": scores,
            "primary_expert": ordered[0],
            "secondary_expert": ordered[1] if scores[ordered[0]] < self.confidence_threshold else None,
            "top1_probability": scores[ordered[0]],
            "model_scope": "public policy-supervised router",
        }
