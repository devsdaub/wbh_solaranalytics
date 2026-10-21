from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.analytics.modelle import faustregel_nachgefuehrt, nachfuehren
from app.analytics.prognose import _symbol, berechne_spanne


def reihe(ertraege: list[float], gti: list[float], standort: list[int] | None = None) -> pd.DataFrame:
    tage = [date(2026, 5, 1) + timedelta(days=i) for i in range(len(ertraege))]
    return pd.DataFrame({
        "date": tage,
        "production_kwh": ertraege,
        "gti_kwh_m2": gti,
        "standort": standort or [0] * len(ertraege),
    })


def test_nachgefuehrte_faustregel_sieht_nicht_in_die_zukunft():
    """Bei Abstand 2 darf der Ausreißer am Vortag des Zieltags nicht eingehen, bei Abstand 1 schon."""
    frame = reihe([2.0] * 18 + [40.0, 40.0], [4.0] * 20)

    assert faustregel_nachgefuehrt(frame, fenster=1, abstand=2)[19] == pytest.approx(2.0)
    assert faustregel_nachgefuehrt(frame, fenster=1, abstand=1)[19] == pytest.approx(40.0)


def test_nachgefuehrte_faustregel_nimmt_den_median_der_letzten_14_tage():
    ertraege = [1.0] * 10 + [3.0] * 14 + [0.0]
    frame = reihe(ertraege, [2.0] * 25)

    assert faustregel_nachgefuehrt(frame)[24] == pytest.approx(3.0)


def test_nach_dem_umzug_zaehlt_der_neue_standort_sobald_er_messwerte_hat():
    ertraege = [1.0] * 20 + [3.0] * 6 + [0.0]
    frame = reihe(ertraege, [2.0] * 27, standort=[0] * 20 + [1] * 7)

    prognose = faustregel_nachgefuehrt(frame)

    assert prognose[20] == pytest.approx(1.0)
    assert prognose[21] == pytest.approx(3.0)
    assert prognose[26] == pytest.approx(3.0)


def test_eigene_quote_fuer_eine_andere_zielspalte():
    frame = reihe([2.0] * 10, [4.0] * 10).assign(morgen=[1.0] * 10)

    quote = faustregel_nachgefuehrt(frame, gti_ziel_spalte="morgen")

    assert quote[-1] == pytest.approx(0.5)


def test_nachfuehrung_wird_begrenzt():
    """Liegt die Prognose dauerhaft bei einem Viertel, korrigiert die Nachführung höchstens um 1,6."""
    frame = reihe([4.0] * 20, [4.0] * 20)
    prognose = np.full(20, 1.0)

    korrigiert = nachfuehren(frame, prognose)

    assert korrigiert[0] == pytest.approx(1.0)
    assert korrigiert[-1] == pytest.approx(1.6)


def test_spanne_aus_abweichungen_in_kwh():
    verlauf = pd.DataFrame({
        "zieltag": [date(2026, 5, 1) + timedelta(days=i) for i in range(30)],
        "standort": 0.0,
        "prognose_kwh": 2.0,
        "ist": 2.0 + np.linspace(-1.0, 1.0, 30),
    })

    unten, oben = berechne_spanne(verlauf, date(2026, 6, 30), 0.0, 3.0)

    assert unten == pytest.approx(3.0 - 0.8, abs=0.01)
    assert oben == pytest.approx(3.0 + 0.8, abs=0.01)


def test_ohne_genug_vorgeschichte_eine_feste_spanne():
    verlauf = pd.DataFrame(columns=["zieltag", "standort", "prognose_kwh", "ist"])

    assert berechne_spanne(verlauf, date(2026, 6, 1), 0.0, 2.0) == pytest.approx((1.2, 3.0))


def test_spanne_wird_nie_negativ():
    verlauf = pd.DataFrame({
        "zieltag": [date(2026, 5, 1) + timedelta(days=i) for i in range(20)],
        "standort": 0.0,
        "prognose_kwh": 2.0,
        "ist": [0.5] * 20,
    })

    unten, _ = berechne_spanne(verlauf, date(2026, 6, 1), 0.0, 0.3)

    assert unten == 0.0


@pytest.mark.parametrize("sonne, regen, erwartet", [
    (9.0, 0.0, "sonne"), (6.0, 0.0, "heiter"), (3.0, 0.0, "wolkig"), (0.5, 0.0, "bedeckt"), (0.5, 8.0, "regen"),
])
def test_wettersymbol_aus_sonnenanteil_und_regen(sonne, regen, erwartet):
    assert _symbol(sonne, 11.0, regen) == erwartet
