import json
from pathlib import Path

import joblib

ARTEFAKTE = Path("analytics_artifacts")
ERGEBNISSE = ARTEFAKTE / "ergebnisse.json"
MODELL = ARTEFAKTE / "modell.joblib"
ABBILDUNGEN = ARTEFAKTE / "abbildungen"


def speichere_ergebnisse(ergebnis: dict) -> None:
    ARTEFAKTE.mkdir(exist_ok=True)
    ERGEBNISSE.write_text(json.dumps(ergebnis, ensure_ascii=False, indent=2), encoding="utf-8")


def speichere_modell(artefakt: dict) -> None:
    ARTEFAKTE.mkdir(exist_ok=True)
    joblib.dump(artefakt, MODELL)


def lade_ergebnisse() -> dict | None:
    if not ERGEBNISSE.exists():
        return None
    return json.loads(ERGEBNISSE.read_text(encoding="utf-8"))


def lade_modell() -> dict | None:
    if not MODELL.exists():
        return None
    return joblib.load(MODELL)
