from __future__ import annotations

import math
import re
from typing import Any


FEATURE_NAMES = [
    "rule_has_numeric",
    "rule_has_comparator",
    "rule_has_unit",
    "indicator_is_numeric",
    "lexical_overlap",
    "rule_has_negation",
    "section_is_interaction",
    "section_is_contraindication",
    "section_is_dosage",
    "severity_is_high",
    "clause_count_scaled",
    "token_count_scaled",
]

_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_COMPARATOR = re.compile(r"less than|greater than|below|above|at least|not exceed|maximum|minimum|every\s+\d+", re.I)
_UNIT = re.compile(r"\b(?:mg|mcg|g|ml|hours?|days?|weeks?|years?|kg|mmhg|inr|ml/min|%)\b", re.I)
_NEGATION = re.compile(r"\b(?:no|not|never|without|contraindicated|avoid)\b", re.I)
_TOKEN = re.compile(r"[a-z0-9]+", re.I)


def extract_router_features(
    rule_text: str,
    section: str,
    severity: str,
    indicator_text: str,
    indicator_value: Any = None,
) -> list[float]:
    rule_tokens = set(_TOKEN.findall(rule_text.lower()))
    indicator_tokens = set(_TOKEN.findall(indicator_text.lower()))
    overlap = len(rule_tokens & indicator_tokens) / max(1, len(rule_tokens | indicator_tokens))
    numeric_indicator = isinstance(indicator_value, (int, float)) and not isinstance(indicator_value, bool)
    if numeric_indicator:
        numeric_indicator = math.isfinite(float(indicator_value))
    section_text = section.lower()
    clauses = max(1, len(re.findall(r"[,;:]|\b(?:and|or|unless|except|if)\b", rule_text, re.I)) + 1)
    return [
        float(bool(_NUMBER.search(rule_text))),
        float(bool(_COMPARATOR.search(rule_text))),
        float(bool(_UNIT.search(rule_text))),
        float(numeric_indicator),
        overlap,
        float(bool(_NEGATION.search(rule_text))),
        float("interaction" in section_text),
        float("contraindication" in section_text),
        float("dosage" in section_text or "administration" in section_text),
        float(severity.lower() in {"high", "critical"}),
        min(clauses, 12) / 12.0,
        min(len(rule_tokens), 120) / 120.0,
    ]
