import numpy as np

from app.analytics.artefakte import lade_ergebnisse
from app.analytics.bewertung import NACHGEFUEHRTE_LERNVERFAHREN, dm_test
from app.analytics.modelle import LERNVERFAHREN

STANDARD = "faustregel_nachgefuehrt"
KANDIDATEN = [STANDARD] + LERNVERFAHREN + NACHGEFUEHRTE_LERNVERFAHREN
SIGNIFIKANZNIVEAU = 0.05


def waehle_verfahren(ist: np.ndarray, prognosen: dict[str, np.ndarray], maske: np.ndarray,
                     mae: dict[str, float], bisher: str | None = None) -> dict:
    """Wechselt nur, wenn das genaueste Verfahren laut Diebold-Mariano signifikant besser ist als das bisherige."""
    bisher = bisher if bisher in KANDIDATEN and bisher in mae else STANDARD
    bestes = min((name for name in KANDIDATEN if name in mae), key=mae.get)
    entscheidung = {"bisher": bisher, "herausforderer": bestes, "statistik": None, "p_wert": None,
                    "signifikanzniveau": SIGNIFIKANZNIVEAU}
    if bestes == bisher:
        return {**entscheidung, "verfahren": bisher, "gewechselt": False,
                "grund": "Das bisherige Verfahren ist weiterhin das genaueste."}

    test = dm_test(ist[maske], prognosen[bestes][maske], prognosen[bisher][maske])
    entscheidung.update(statistik=test["statistik"], p_wert=test["p_wert"])
    if test["p_wert"] is not None and test["p_wert"] < SIGNIFIKANZNIVEAU and mae[bestes] < mae[bisher]:
        return {**entscheidung, "verfahren": bestes, "gewechselt": True,
                "grund": "Das neue Verfahren ist signifikant genauer."}
    return {**entscheidung, "verfahren": bisher, "gewechselt": False,
            "grund": "Das genaueste Verfahren ist nicht signifikant besser, das bisherige bleibt."}


def eingesetztes_verfahren() -> str:
    """Verfahren aus dem letzten Analyselauf, ohne Lauf die nachgeführte Faustregel."""
    ergebnisse = lade_ergebnisse() or {}
    verfahren = ergebnisse.get("eingesetzt", {}).get("verfahren")
    return verfahren if verfahren in KANDIDATEN else STANDARD
