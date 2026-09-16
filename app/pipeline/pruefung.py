import logging

import pandas as pd
from sqlalchemy import select

from app.config import load_plant_config
from app.database import engine
from app.models import DailyFact, HourlyWeather

logger = logging.getLogger(__name__)

# Über 1 hiesse, das Modul liefert mehr Energie, als die Einstrahlung hergibt.
EQ_OBERGRENZE = 1.0

# Unterhalb dieses Füllgrads gilt eine Spalte als auffällig.
ABDECKUNG_WARNGRENZE = 0.5


def _zahl(wert):
    """NaN wird zu None, damit die Antwort gültiges JSON ergibt."""
    return None if pd.isna(wert) else round(float(wert), 3)


def pruefe_tageswerte(frame: pd.DataFrame, kapazitaet_w: int) -> list[dict]:
    """Prüft die fertigen Tageswerte auf fachlich unmögliche Kombinationen."""
    if frame.empty:
        return []

    obergrenze = kapazitaet_w * 24 / 1000

    regeln = [
        ("Ertrag ohne Einstrahlung",
         (frame["production_kwh"] > 0) & (frame["gti_kwh"] == 0)),
        (f"Ertrag über {obergrenze:.1f} kWh",
         frame["production_kwh"] > obergrenze),
        ("Wirkungsgrad über 1",
         frame["eq"] > EQ_OBERGRENZE),
        ("Negativer Ertrag",
         frame["production_kwh"] < 0),
    ]

    befunde = []
    for name, treffer in regeln:
        for _, zeile in frame[treffer.fillna(False)].iterrows():
            befunde.append({
                "regel": name,
                "datum": zeile["date"].isoformat(),
                "produktion_kwh": _zahl(zeile["production_kwh"]),
                "gti_kwh": _zahl(zeile["gti_kwh"]),
                "eq": _zahl(zeile["eq"]),
            })

    return sorted(befunde, key=lambda b: b["datum"])


def spalten_abdeckung(frame: pd.DataFrame, ausser: tuple = ()) -> list[dict]:
    """Füllgrad je Spalte, aufsteigend sortiert."""
    gesamt = len(frame)
    if not gesamt:
        return []

    abdeckung = [
        {
            "spalte": spalte,
            "gefuellt": int(frame[spalte].notna().sum()),
            "gesamt": gesamt,
            "anteil": round(float(frame[spalte].notna().mean()), 4),
        }
        for spalte in frame.columns
        if spalte not in ausser
    ]

    return sorted(abdeckung, key=lambda e: e["anteil"])


def _lade_tageswerte(plant_id: int) -> pd.DataFrame:
    statement = select(
        DailyFact.date, DailyFact.production_kwh, DailyFact.gti_kwh, DailyFact.eq
    ).where(DailyFact.plant_id == plant_id)
    return pd.read_sql(statement, engine)


def _lade_stundenwerte(plant_id: int) -> pd.DataFrame:
    statement = select(HourlyWeather).where(HourlyWeather.plant_id == plant_id)
    return pd.read_sql(statement, engine)


def qualitaetsbericht(plant_id: int) -> dict:
    """Sammelt alle fachlichen Befunde zu den gespeicherten Daten."""
    kapazitaet = load_plant_config().panel.capacity_w
    befunde = pruefe_tageswerte(_lade_tageswerte(plant_id), kapazitaet)

    abdeckung = spalten_abdeckung(
        _lade_stundenwerte(plant_id), ausser=("id", "plant_id", "timestamp")
    )
    auffaellig = [e for e in abdeckung if e["anteil"] < ABDECKUNG_WARNGRENZE]

    if befunde:
        logger.warning("Plausibilitätsprüfung: %s Befund(e)", len(befunde))
    for eintrag in auffaellig:
        logger.warning("Spalte %s ist nur zu %.0f %% gefüllt",
                       eintrag["spalte"], eintrag["anteil"] * 100)

    return {
        "befunde": befunde,
        "anzahl": len(befunde),
        "abdeckung": abdeckung,
        "auffaellige_spalten": [e["spalte"] for e in auffaellig],
    }
