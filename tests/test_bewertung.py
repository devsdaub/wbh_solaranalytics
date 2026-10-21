import numpy as np
import pandas as pd
import pytest

from app.analytics.bewertung import (
    ablationskonfigurationen,
    dm_test,
    kennzahlen,
    schema_s1,
    schema_s2,
)


def tage(anzahl: int, beginn: str = "2025-05-01") -> pd.DataFrame:
    return pd.DataFrame({"date": pd.date_range(beginn, periods=anzahl, freq="D").date})


def test_faltungen_ueberschneiden_sich_nicht():
    """Kein Trainingstag darf zeitlich hinter einem Testtag liegen."""
    for schema in (schema_s1, schema_s2):
        for training_idx, test_idx in schema(tage(400)):
            assert max(training_idx) < min(test_idx)


def test_kurze_reihen_bekommen_weniger_faltungen():
    assert len(schema_s1(tage(150))) == 2
    assert len(schema_s1(tage(600))) == 5


def test_s2_testet_ganze_monate_erst_ab_150_trainingstagen():
    faltungen = schema_s2(tage(400))
    frame = tage(400)

    assert all(len(training) >= 150 for training, _ in faltungen)
    for _, test_idx in faltungen:
        monate = {(t.year, t.month) for t in frame["date"].iloc[test_idx]}
        assert len(monate) == 1


def test_kennzahlen_mit_bekannten_werten():
    ist = np.array([2.0, 4.0, np.nan, 1.0])
    prognose = np.array([3.0, 3.0, 5.0, 1.0])

    werte = kennzahlen(ist, prognose)

    assert werte["n"] == 3
    assert werte["mae"] == pytest.approx(2 / 3, abs=1e-3)
    assert werte["rmse"] == pytest.approx(np.sqrt(2 / 3), abs=1e-3)
    assert werte["bias_prozent"] == pytest.approx(0.0)


def test_diebold_mariano_erkennt_ein_klar_besseres_verfahren():
    zufall = np.random.default_rng(1)
    ist = zufall.uniform(0, 4, 200)
    gut = ist + zufall.normal(0, 0.2, 200)
    schlecht = ist + zufall.normal(0, 0.8, 200)

    test = dm_test(ist, gut, schlecht)

    assert test["statistik"] < 0
    assert test["p_wert"] < 0.01


def test_ablation_laesst_den_standort_immer_drin():
    konfigurationen = ablationskonfigurationen()

    assert len(konfigurationen) == 9
    assert all("standort" in spalten for _, spalten in konfigurationen)
    ohne_satellit = dict(konfigurationen)["ohne satellit"]
    assert "gti_satellit_kwh_m2" not in ohne_satellit
