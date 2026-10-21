import numpy as np

from app.analytics import auswahl
from app.analytics.auswahl import STANDARD, waehle_verfahren


def lage(fehler_regel: float, fehler_wald: float, tage: int = 200, streuung: float = 0.3):
    """Ist-Werte und zwei Prognosen mit vorgegebenem mittlerem Fehler, die übrigen Kandidaten deutlich schlechter."""
    rng = np.random.default_rng(1)
    ist = rng.uniform(0.5, 4.5, tage)
    def prognose(fehler):
        return ist + rng.choice([-1, 1], tage) * np.abs(rng.normal(fehler, streuung, tage))
    prognosen = {name: prognose(1.5) for name in auswahl.KANDIDATEN}
    prognosen[STANDARD] = prognose(fehler_regel)
    prognosen["random_forest_nachgefuehrt"] = prognose(fehler_wald)
    maske = np.ones(tage, dtype=bool)
    mae = {name: float(np.mean(np.abs(werte - ist))) for name, werte in prognosen.items()}
    return ist, prognosen, maske, mae


def test_bisheriges_bleibt_wenn_es_das_genaueste_ist():
    ergebnis = waehle_verfahren(*lage(0.3, 0.5), bisher=STANDARD)
    assert ergebnis["verfahren"] == STANDARD
    assert not ergebnis["gewechselt"]


def test_wechsel_wenn_herausforderer_signifikant_besser():
    ergebnis = waehle_verfahren(*lage(0.6, 0.3), bisher=STANDARD)
    assert ergebnis["verfahren"] == "random_forest_nachgefuehrt"
    assert ergebnis["gewechselt"]
    assert ergebnis["p_wert"] < auswahl.SIGNIFIKANZNIVEAU


def test_kein_wechsel_bei_knappem_vorsprung():
    ist, prognosen, maske, mae = lage(0.4, 1.5)
    # nur an drei Tagen besser, sonst gleich: DM-Statistik -3/sqrt(3), also p rund 0,08
    knapp = prognosen[STANDARD].copy()
    for tag in (10, 50, 90):
        knapp[tag] = ist[tag] + 0.5 * (knapp[tag] - ist[tag])
    prognosen["random_forest_nachgefuehrt"] = knapp
    mae["random_forest_nachgefuehrt"] = float(np.mean(np.abs(knapp - ist)))

    ergebnis = waehle_verfahren(ist, prognosen, maske, mae, bisher=STANDARD)
    assert ergebnis["herausforderer"] == "random_forest_nachgefuehrt"
    assert ergebnis["p_wert"] > auswahl.SIGNIFIKANZNIVEAU
    assert ergebnis["verfahren"] == STANDARD
    assert not ergebnis["gewechselt"]


def test_unbekanntes_bisheriges_faellt_auf_die_faustregel_zurueck():
    ergebnis = waehle_verfahren(*lage(0.3, 0.5), bisher="klimatologie")
    assert ergebnis["bisher"] == STANDARD


def test_ohne_analyselauf_rechnet_die_prognose_mit_der_faustregel(monkeypatch):
    monkeypatch.setattr(auswahl, "lade_ergebnisse", lambda: None)
    assert auswahl.eingesetztes_verfahren() == STANDARD
    monkeypatch.setattr(auswahl, "lade_ergebnisse", lambda: {"eingesetzt": {"verfahren": "xgboost"}})
    assert auswahl.eingesetztes_verfahren() == "xgboost"
