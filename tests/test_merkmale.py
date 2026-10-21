from datetime import date

import pandas as pd
import pytest

from app.analytics.merkmale import bestimme_wetterlage, verdichte_auf_tage


def stundenframe(start: str, stunden: int) -> pd.DataFrame:
    """Lückenlose Stundenwerte ab einem UTC-Zeitpunkt, Sichtweite leer wie im Archiv."""
    return pd.DataFrame({
        "timestamp": pd.date_range(start, periods=stunden, freq="h", tz="UTC"),
        "gti": [100.0] * stunden,
        "temperature": [20.0] * stunden,
        "cloud_cover": [50] * stunden,
        "cloud_cover_low": [20] * stunden,
        "cloud_cover_mid": [20] * stunden,
        "cloud_cover_high": [20] * stunden,
        "visibility": [None] * stunden,
        "sunshine_duration": [1800.0] * stunden,
        "dust": [1.0] * stunden,
        "pm10": [10.0] * stunden,
        "aerosol_od": [0.1] * stunden,
    })


def tag(**werte) -> pd.Series:
    zeile = {
        "staub_max": 2.0, "wolken_mittel": 50.0, "wolken_tief": 20.0,
        "wolken_streuung": 10.0, "sicht_km": float("nan"), "sonnenstunden": 5.0,
    }
    zeile.update(werte)
    return pd.Series(zeile)


def test_lokaler_tag_beginnt_im_sommer_um_22_uhr_utc():
    """Der Ertrag bezieht sich auf den Berliner Kalendertag. 22:00 UTC am
    30.06. ist dort schon Mitternacht des 01.07."""
    taeglich = verdichte_auf_tage(stundenframe("2026-06-30 22:00", 24))

    assert list(taeglich["date"]) == [date(2026, 7, 1)]


def test_einstrahlung_und_sonnenscheindauer_in_tageseinheiten():
    """24 Stunden mit 100 W/m² sind 2,4 kWh/m², 24 halbe Sonnenstunden
    sind 12 Stunden."""
    taeglich = verdichte_auf_tage(stundenframe("2026-06-30 22:00", 24))

    assert taeglich["gti_kwh_m2"].iloc[0] == pytest.approx(2.4)
    assert taeglich["sonnenstunden"].iloc[0] == pytest.approx(12.0)


def test_tag_mit_zu_wenigen_stunden_wird_verworfen():
    """Zwölf Stundenwerte ergäben eine halbe Einstrahlungssumme, und der Tag
    ginge als trüber Tag durch, obwohl nur Daten fehlen."""
    taeglich = verdichte_auf_tage(stundenframe("2026-06-30 22:00", 12))

    assert taeglich.empty


def test_staub_hat_vorrang_vor_bewoelkung():
    zeile = tag(staub_max=30.0, wolken_mittel=90.0)

    assert bestimme_wetterlage(zeile, staub_schwelle=5.0) == "saharastaub"


def test_hochnebel_ohne_sichtweite_ueber_die_ersatzregel():
    """Die Sichtweite fehlt im Archiv. Dominiert tiefe Bewölkung und scheint
    praktisch keine Sonne, gilt der Tag trotzdem als Hochnebel."""
    zeile = tag(wolken_tief=90.0, wolken_mittel=90.0, sonnenstunden=0.2)

    assert bestimme_wetterlage(zeile, staub_schwelle=5.0) == "hochnebel"


def test_tiefe_wolken_mit_sonne_sind_kein_hochnebel():
    zeile = tag(wolken_tief=90.0, wolken_mittel=90.0, sonnenstunden=3.0)

    assert bestimme_wetterlage(zeile, staub_schwelle=5.0) == "bedeckt"


def test_bewoelkungsklassen():
    assert bestimme_wetterlage(tag(wolken_mittel=10.0), 5.0) == "klar"
    assert bestimme_wetterlage(tag(wolken_mittel=90.0), 5.0) == "bedeckt"
    assert bestimme_wetterlage(tag(wolken_streuung=40.0), 5.0) == "wechselhaft"
    assert bestimme_wetterlage(tag(), 5.0) == "gemischt"


def test_sichtweite_kommt_in_metern_und_wird_zu_kilometern():
    stunden = stundenframe("2026-06-30 22:00", 24)
    stunden["visibility"] = 5000.0

    assert verdichte_auf_tage(stunden)["sicht_km"].iloc[0] == pytest.approx(5.0)


def test_hochnebel_ueber_die_sichtweite():
    zeile = tag(wolken_tief=90.0, wolken_mittel=90.0, sicht_km=3.0, sonnenstunden=4.0)

    assert bestimme_wetterlage(zeile, staub_schwelle=5.0) == "hochnebel"


def test_satellit_braucht_einen_fast_vollstaendigen_tag():
    """SARAH-3 hängt einige Tage hinterher, ein angebrochener Tag darf nicht als trüb zählen."""
    stunden = stundenframe("2026-06-30 22:00", 24)
    stunden["gti_satellit"] = [200.0] * 10 + [None] * 14

    assert pd.isna(verdichte_auf_tage(stunden)["gti_satellit_kwh_m2"].iloc[0])


def test_vorhersage_ohne_wolkenschichten_wird_trotzdem_verdichtet():
    stunden = stundenframe("2026-06-30 22:00", 24)[["timestamp", "gti", "temperature", "cloud_cover", "sunshine_duration"]]

    taeglich = verdichte_auf_tage(stunden)

    assert taeglich["gti_kwh_m2"].iloc[0] == pytest.approx(2.4)
    assert taeglich["wolken_tief"].isna().all()
