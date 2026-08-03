from __future__ import annotations

import json
from pathlib import Path

from rdkit import Chem, DataStructs, rdBase
from rdkit.Chem import AllChem, MACCSkeys, rdFingerprintGenerator, rdMolAlign, rdShapeHelpers


class MolecularEvidence:
    def __init__(self, path: Path | None = None, threshold: float = 0.40) -> None:
        source = path or Path(__file__).with_name("data") / "public_structures.json"
        self.payload = json.loads(source.read_text(encoding="utf-8"))
        self.structures = self.payload["structures"]
        self.threshold = threshold
        self.morgan = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)

    def compare(self, target_drug: str, reference_drug: str) -> dict:
        target = self._record(target_drug)
        reference = self._record(reference_drug)
        if target is None or reference is None:
            return {"available": False, "target_drug": target_drug, "reference_drug": reference_drug, "escalate": False}
        target_mol = Chem.MolFromSmiles(target["smiles"])
        reference_mol = Chem.MolFromSmiles(reference["smiles"])
        if target_mol is None or reference_mol is None:
            return {"available": False, "target_drug": target_drug, "reference_drug": reference_drug, "escalate": False}
        morgan = DataStructs.TanimotoSimilarity(self.morgan.GetFingerprint(target_mol), self.morgan.GetFingerprint(reference_mol))
        maccs = DataStructs.TanimotoSimilarity(MACCSkeys.GenMACCSKeys(target_mol), MACCSkeys.GenMACCSKeys(reference_mol))
        shape = self._shape_similarity(target_mol, reference_mol)
        return {
            "available": True,
            "target_drug": target_drug,
            "reference_drug": reference_drug,
            "target_pubchem_cid": target["cid"],
            "reference_pubchem_cid": reference["cid"],
            "morgan_tanimoto": round(float(morgan), 4),
            "maccs_tanimoto": round(float(maccs), 4),
            "shape_similarity": None if shape is None else round(float(shape), 4),
            "threshold": self.threshold,
            "escalate": bool(morgan >= self.threshold),
            "source": "PubChem PUG REST",
            "rdkit_version": rdBase.rdkitVersion,
            "representation": "Morgan radius 2, 2048 bits; MACCS; ETKDGv3 fixed seed",
        }

    def _record(self, drug: str) -> dict | None:
        key = drug.lower().replace("extended-release", "").replace("extended release", "").strip()
        aliases = {"penicillin": "penicillin", "nifedipine gits": "nifedipine"}
        return self.structures.get(aliases.get(key, key))

    @staticmethod
    def _shape_similarity(first: Chem.Mol, second: Chem.Mol) -> float | None:
        first = Chem.AddHs(first)
        second = Chem.AddHs(second)
        params = AllChem.ETKDGv3()
        params.randomSeed = 20260115
        if AllChem.EmbedMolecule(first, params) != 0 or AllChem.EmbedMolecule(second, params) != 0:
            return None
        AllChem.MMFFOptimizeMolecule(first, maxIters=200)
        AllChem.MMFFOptimizeMolecule(second, maxIters=200)
        try:
            rdMolAlign.GetO3A(second, first).Align()
            return 1.0 - rdShapeHelpers.ShapeTanimotoDist(first, second)
        except RuntimeError:
            return None
