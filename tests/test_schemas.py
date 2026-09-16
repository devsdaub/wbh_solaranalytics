import pandas as pd
import pytest
from pandera.errors import SchemaError, SchemaErrors

from app.schemas import (
    ENERGY_REPORT_SCHEMA,
    HOURLY_AIR_SCHEMA,
    HOURLY_WEATHER_SCHEMA,
    validiere_nachsichtig,
)


def wetterframe(**abweichungen) -> pd.DataFrame:
    """Gültiger Wetterframe mit zwei Stunden, per Schlüsselwort verbiegbar."""
    spalten = {
        "plant_id": [1, 1],
        "timestamp": pd.to_datetime(
            ["2026-06-01 10:00", "2026-06-01 11:00"]
        ).tz_localize("UTC"),
        "gti": [420.5, 511.0],
        "temperature": [21.3, 22.8],
        "cloud_cover": [40, 35],
        "cloud_cover_low": [10, 5],
        "cloud_cover_mid": [20, 20],
        "cloud_cover_high": [30, 25],
        "visibility": [None, None],
        "sunshine_duration": [3600.0, 2400.0],
    }
    spalten.update(abweichungen)
    return pd.DataFrame(spalten)


def luftframe(**abweichungen) -> pd.DataFrame:
    spalten = {
        "plant_id": [1, 1],
        "timestamp": pd.to_datetime(
            ["2026-06-01 10:00", "2026-06-01 11:00"]
        ).tz_localize("UTC"),
        "dust": [1.0, 1.0],
        "pm10": [22.3, 25.5],
        "aerosol_od": [0.10, 0.09],
    }
    spalten.update(abweichungen)
    return pd.DataFrame(spalten)


def test_gueltiger_wetterframe_geht_durch():
    geprueft = HOURLY_WEATHER_SCHEMA.validate(wetterframe())

    assert len(geprueft) == 2
    assert str(geprueft["timestamp"].dtype) == "datetime64[ns, UTC]"


def test_fehlende_spalte_faellt_auf():
    with pytest.raises(SchemaError):
        HOURLY_WEATHER_SCHEMA.validate(wetterframe().drop(columns=["gti"]))


def test_zusaetzliche_spalte_faellt_auf():
    """strict=True. Der Verstoss kommt als SchemaErrors, auch ohne lazy."""
    mit_extra = wetterframe().assign(schneehoehe=[0.0, 0.0])

    with pytest.raises(SchemaErrors):
        HOURLY_WEATHER_SCHEMA.validate(mit_extra)


def test_unmoegliche_temperatur_faellt_auf():
    with pytest.raises(SchemaError):
        HOURLY_WEATHER_SCHEMA.validate(wetterframe(temperature=[99.0, 22.8]))


def test_sonnenscheindauer_ueber_einer_stunde_faellt_auf():
    """Open-Meteo liefert Sekunden je Stunde. Mehr als 3600 heisst,
    die Einheit hat sich geändert."""
    with pytest.raises(SchemaError):
        HOURLY_WEATHER_SCHEMA.validate(wetterframe(sunshine_duration=[3700.0, 2400.0]))


def test_gueltiger_luftframe_geht_durch():
    geprueft = HOURLY_AIR_SCHEMA.validate(luftframe())

    assert len(geprueft) == 2


def test_negative_aerosole_fallen_auf():
    with pytest.raises(SchemaError):
        HOURLY_AIR_SCHEMA.validate(luftframe(aerosol_od=[-0.1, 0.09]))


def test_produktion_darf_nicht_leer_sein():
    """Bei der Produktion ist ein fehlender Wert ein Fehler, kein Messausfall."""
    frame = pd.DataFrame({
        "plant_id": [1],
        "date": pd.to_datetime(["2026-06-01"]),
        "production_kwh": [None],
    })

    with pytest.raises((SchemaError, SchemaErrors)):
        ENERGY_REPORT_SCHEMA.validate(frame)


def test_ausreisser_wird_null_und_die_zeile_bleibt():
    """Zeilen zu verwerfen würde den Tag unvollständig machen und den
    Backfill bei jedem Lauf erneut auslösen."""
    frame = wetterframe(temperature=[99.0, 22.8])

    geprueft = validiere_nachsichtig(HOURLY_WEATHER_SCHEMA, frame, "test")

    assert len(geprueft) == 2
    assert pd.isna(geprueft["temperature"].iloc[0])
    assert geprueft["gti"].iloc[0] == 420.5


def test_fehlende_spalte_wird_nicht_geheilt():
    """Strukturelle Abweichungen heissen, die Schnittstelle hat sich geändert."""
    frame = wetterframe().drop(columns=["temperature"])

    with pytest.raises(SchemaErrors):
        validiere_nachsichtig(HOURLY_WEATHER_SCHEMA, frame, "test")
