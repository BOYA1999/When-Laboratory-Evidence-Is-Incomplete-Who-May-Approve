import math


class CalcMCPServer:
    name = "Calc-MCP-Server"

    def calculate_egfr(self, age: int, sex: str, scr_umol_l: float) -> dict:
        scr_mg_dl = scr_umol_l / 88.4
        female = sex.strip().lower() in {"f", "female", "woman", "女"}
        kappa = 0.7 if female else 0.9
        alpha = -0.241 if female else -0.302
        sex_factor = 1.012 if female else 1.0
        egfr = (
            142
            * min(scr_mg_dl / kappa, 1) ** alpha
            * max(scr_mg_dl / kappa, 1) ** -1.2
            * 0.9938 ** age
            * sex_factor
        )
        return {"egfr": round(egfr, 1), "stage": self._ckd_stage(egfr), "unit": "mL/min/1.73m2"}

    def calculate_crcl(self, age: int, sex: str, scr_umol_l: float, weight_kg: float) -> dict:
        scr_mg_dl = scr_umol_l / 88.4
        factor = 0.85 if sex.strip().lower() in {"f", "female", "woman", "女"} else 1.0
        crcl = ((140 - age) * weight_kg * factor) / (72 * scr_mg_dl)
        return {"crcl": round(crcl, 1), "unit": "mL/min"}

    def verify_daily_dose(self, dose_mg: float | None, frequency: str | None) -> dict:
        if dose_mg is None:
            return {"daily_dose_mg": None, "frequency_multiplier": None}
        multiplier = self._frequency_multiplier(frequency)
        return {"daily_dose_mg": dose_mg * multiplier, "frequency_multiplier": multiplier}

    @staticmethod
    def _ckd_stage(egfr: float) -> str:
        if egfr >= 90:
            return "G1"
        if egfr >= 60:
            return "G2"
        if egfr >= 45:
            return "G3a"
        if egfr >= 30:
            return "G3b"
        if egfr >= 15:
            return "G4"
        return "G5"

    @staticmethod
    def _frequency_multiplier(frequency: str | None) -> float:
        if not frequency:
            return 1.0
        text = frequency.lower().replace(" ", "")
        mapping = {"qd": 1, "bid": 2, "tid": 3, "qid": 4, "q12h": 2, "q8h": 3, "q6h": 4}
        if text in mapping:
            return float(mapping[text])
        if text.startswith("q") and text.endswith("h"):
            try:
                hours = float(text[1:-1])
                return 24.0 / hours if hours > 0 else 1.0
            except ValueError:
                return 1.0
        if "daily" in text or "once" in text:
            return 1.0
        return 1.0


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

