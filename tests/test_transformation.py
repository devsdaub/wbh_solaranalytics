from datetime import date

import pandas as pd

from app.pipeline.transformation import (
    aggregate_hourly,
    finde_luecken,
    finde_wetterluecken,
    zu_bloecken,
)


def stundenframe(start: str, stunden: int) -> pd.DataFrame:
    """Lückenlose Stundenwerte ab einem UTC-Zeitpunkt."""
    return pd.DataFrame({
        "timestamp": pd.date_range(start, periods=stunden, freq="h", tz="UTC"),
        "gti": [100.0] * stunden,
        "temperature": [20.0] * stunden,
        "cloud_cover": [50] * stunden,
        "dust": [1.0] * stunden,
        "pm10": [10.0] * stunden,
    })


def test_utc_tag_ergibt_keinen_vollen_lokalen_tag():
    """Berlin liegt im Sommer zwei Stunden vor UTC. 24 UTC-Stunden decken
    deshalb 22 Stunden des einen und 2 des nächsten lokalen Tages ab."""
    taeglich = aggregate_hourly(stundenframe("2026-06-01 00:00", 24), plant_id=1)

    assert dict(zip(taeglich["date"], taeglich["hours"])) == {
        date(2026, 6, 1): 22,
        date(2026, 6, 2): 2,
    }


def test_um_einen_tag_erweitert_wird_es_ein_voller_tag():
    """Genau deshalb erweitert der Backfill seinen Abrufbereich."""
    taeglich = aggregate_hourly(stundenframe("2026-05-31 22:00", 24), plant_id=1)

    voll = taeglich[taeglich["date"] == date(2026, 6, 1)]
    assert voll["hours"].iloc[0] == 24


def test_tag_der_zeitumstellung_hat_dreiundzwanzig_stunden():
    """Am 29.03.2026 entfällt 02:00 Ortszeit. Darum ist die Schwelle 23."""
    taeglich = aggregate_hourly(stundenframe("2026-03-28 23:00", 48), plant_id=1)

    umstellung = taeglich[taeglich["date"] == date(2026, 3, 29)]
    assert umstellung["hours"].iloc[0] == 23


def test_tag_ganz_ohne_messwerte_bleibt_leer():
    """pandas summiert lauter NaN zu 0. min_count=1 verhindert, dass daraus
    ein gemessener Nullertrag wird, wo nichts gemessen wurde."""
    frame = stundenframe("2026-05-31 22:00", 24)
    frame["gti"] = None

    taeglich = aggregate_hourly(frame, plant_id=1)

    voll = taeglich[taeglich["date"] == date(2026, 6, 1)]
    assert pd.isna(voll["gti_kwh"].iloc[0])


def test_zu_bloecken_einzelner_tag():
    """Die Schleife läuft hier nie durch, nur das abschliessende append."""
    assert zu_bloecken([date(2026, 3, 5)]) == [
        {"von": date(2026, 3, 5), "bis": date(2026, 3, 5), "tage": 1}
    ]


def test_zu_bloecken_trennt_bei_luecke():
    tage = [date(2026, 3, n) for n in (1, 2, 9, 10, 20)]

    bloecke = zu_bloecken(tage)

    assert [b["tage"] for b in bloecke] == [2, 2, 1]
    assert bloecke[1]["von"] == date(2026, 3, 9)


def test_luecke_ohne_zeile_wird_gefunden():
    """Zu einem Tag ganz ohne Wetterdaten gibt es keine Zeile in
    daily_facts. Wird nur gegen die vorhandenen Zeilen gesucht, bleibt so
    eine Lücke unsichtbar, obwohl gerade dort die Produktion fehlt."""
    frame = pd.DataFrame({
        "date": [date(2026, 3, 1), date(2026, 3, 5)],
        "production_kwh": [1.0, 2.0],
    })

    luecken = finde_luecken(frame)

    assert luecken == [{"von": date(2026, 3, 2), "bis": date(2026, 3, 4), "tage": 3}]


def test_luecke_nur_innerhalb_des_messzeitraums():
    """Was nach der letzten Messung kommt, fehlt nicht, es ist noch nicht da."""
    frame = pd.DataFrame({
        "date": [date(2026, 3, 1), date(2026, 3, 3)],
        "production_kwh": [1.0, None],
    })

    assert finde_luecken(frame) == []


def test_wetterluecke_braucht_einen_produktionswert():
    """Ohne diese Bedingung würde der Backfill den angebrochenen Randtag
    bei jedem Lauf erneut abrufen."""
    frame = pd.DataFrame({
        "date": [date(2026, 3, 1), date(2026, 3, 2)],
        "production_kwh": [3.0, None],
        "hours": [None, 2],
    })

    luecken = finde_wetterluecken(frame)

    assert [b["von"] for b in luecken] == [date(2026, 3, 1)]
