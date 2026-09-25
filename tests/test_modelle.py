from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.analytics.modelle import baue_modelle, faustregel, klimatologie, persistenz


def tage(daten: list[date], ertraege: list[float],
         gti: list[float] | None = None) -> pd.DataFrame:
    frame = pd.DataFrame({"date": daten, "production_kwh": ertraege})
    if gti is not None:
        frame["gti_kwh_m2"] = gti
    return frame


def test_persistenz_nimmt_nach_einer_luecke_den_letzten_messtag():
    training = tage([date(2026, 5, 1), date(2026, 5, 2)], [2.0, 3.0])
    test = tage([date(2026, 5, 6), date(2026, 5, 7)], [4.0, 5.0])

    assert persistenz(training, test) == pytest.approx([3.0, 4.0])


def test_klimatologie_sieht_ueber_den_jahreswechsel_und_nur_ins_training():
    training = tage([date(2025, 12, 28), date(2025, 7, 1)], [0.5, 4.0])
    test = tage([date(2026, 1, 3)], [9.0])

    assert klimatologie(training, test) == pytest.approx([0.5])


def test_faustregel_skaliert_die_medianquote_des_trainings():
    training = tage([date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3)],
                    [2.0, 2.5, 3.0], gti=[5.0, 5.0, 5.0])
    test = tage([date(2026, 5, 4), date(2026, 5, 5)], [9.0, 9.0], gti=[6.0, 2.0])

    assert faustregel(training, test) == pytest.approx([3.0, 1.0])


def test_faustregel_begrenzt_die_quote_dunkler_tage():
    training = tage([date(2026, 12, 1), date(2026, 12, 2), date(2026, 12, 3)],
                    [2.0, 0.05, 0.06], gti=[4.0, 0.001, 0.001])
    test = tage([date(2026, 12, 4)], [None], gti=[4.0])

    assert faustregel(training, test) == pytest.approx([1.6])


def test_alle_drei_pipelines_lernen_und_prognostizieren():
    zufall = np.random.default_rng(42)
    X = pd.DataFrame(zufall.uniform(0, 1, (60, 3)), columns=["a", "b", "c"])
    y = 3.0 * X["a"] + zufall.normal(0, 0.1, 60)
    X.iloc[0, 1] = np.nan

    for name, pipeline in baue_modelle().items():
        prognose = pipeline.fit(X, y).predict(X)
        assert prognose.shape == (60,), name
        assert np.isfinite(prognose).all(), name
