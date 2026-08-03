from __future__ import annotations

from .models import Indicator, Rule
from .molecular import MolecularEvidence
from .registry import DrugDomainRegistry, normalize_context_drug


class KBMCPServer:
    name = "KB-MCP-Server"

    def __init__(self, registry: DrugDomainRegistry | None = None) -> None:
        self.registry = registry or DrugDomainRegistry()
        self.molecular = MolecularEvidence()

    def retrieve_rules(self, target_drugs: list[str], indicators: list[Indicator]) -> list[Rule]:
        indicator_terms = {term for indicator in indicators for term in indicator.keywords}
        retrieved = []
        for rule in self.registry.rules_for(target_drugs):
            interaction_drugs = {term.removeprefix("drug:") for term in rule.keywords if term.startswith("drug:")}
            context_drugs = {term.removeprefix("drug:") for term in indicator_terms if term.startswith("drug:")}
            interaction_hit = bool(interaction_drugs) and interaction_drugs.issubset(context_drugs)
            keyword_hit = bool(set(rule.keywords).intersection(indicator_terms))
            if keyword_hit or interaction_hit or rule.high_risk:
                retrieved.append(rule)
        return _deduplicate(retrieved)

    def analyze_molecular_similarity(self, target_drug: str, allergies: list[dict]) -> list[dict]:
        results = []
        for allergy in allergies:
            allergen = normalize_context_drug(str(allergy.get("drug", "")))
            comparison = self.molecular.compare(target_drug, allergen)
            comparison["allergy_reaction"] = allergy.get("reaction")
            results.append(comparison)
        return results


def _deduplicate(rules: list[Rule]) -> list[Rule]:
    return list({rule.id: rule for rule in rules}.values())
