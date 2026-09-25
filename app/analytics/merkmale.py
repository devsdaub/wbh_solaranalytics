import logging

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.sonnenstand import sonnenstand_merkmale
from app.config import load_plant_config
from app.models import DailyFact, HourlyWeather

logger = logging.getLogger(__name__)

MERKMALSGRUPPEN: dict[str, list[str]] = {
    "wetter": [
        "gti_kwh_m2", "temp_mittel", "temp_max",
        "wolken_mittel", "wolken_tief", "wolken_mittelhoch", "wolken_hoch",
        "wolken_streuung", "sicht_mittel", "sicht_min", "sonnenstunden",
    ],
    "luftqualitaet": ["staub_max", "staub_mittel", "pm10_mittel", "aerosol_mittel"],
    "sonnenstand": ["tageslaenge_h", "mittagshoehe_grad", "jahrestag_sin", "jahrestag_cos"],
}

ALLE_MERKMALE = [s for spalten in MERKMALSGRUPPEN.values() for s in spalten]
ZIELGROESSE = "production_kwh"

MIN_STUNDEN = 20
AUSFALL_SCHWELLE_KWH = 0.05


def _lade_produktion(session: Session, plant_id: int) -> pd.DataFrame:
    zeilen = session.execute(
        select(DailyFact.date, DailyFact.production_kwh)
        .where(DailyFact.plant_id == plant_id, DailyFact.production_kwh.isnot(None))
        .order_by(DailyFact.date)
    ).all()
    return pd.DataFrame(zeilen, columns=["date", "production_kwh"])


def _lade_stundenwerte(session: Session, plant_id: int) -> pd.DataFrame:
    zeilen = session.execute(
        select(
            HourlyWeather.timestamp, HourlyWeather.gti, HourlyWeather.temperature,
            HourlyWeather.cloud_cover, HourlyWeather.cloud_cover_low,
            HourlyWeather.cloud_cover_mid, HourlyWeather.cloud_cover_high,
            HourlyWeather.visibility, HourlyWeather.sunshine_duration,
            HourlyWeather.dust, HourlyWeather.pm10, HourlyWeather.aerosol_od,
        )
        .where(HourlyWeather.plant_id == plant_id)
        .order_by(HourlyWeather.timestamp)
    ).all()
    return pd.DataFrame(zeilen, columns=[
        "timestamp", "gti", "temperature", "cloud_cover", "cloud_cover_low",
        "cloud_cover_mid", "cloud_cover_high", "visibility", "sunshine_duration",
        "dust", "pm10", "aerosol_od",
    ])


def verdichte_auf_tage(stunden: pd.DataFrame) -> pd.DataFrame:
    frame = stunden.copy()
    zeit = pd.to_datetime(frame["timestamp"], utc=True)
    frame["date"] = zeit.dt.tz_convert("Europe/Berlin").dt.date

    taeglich = frame.groupby("date").agg(
        gti_wh_m2=("gti", "sum"),
        temp_mittel=("temperature", "mean"),
        temp_max=("temperature", "max"),
        wolken_mittel=("cloud_cover", "mean"),
        wolken_tief=("cloud_cover_low", "mean"),
        wolken_mittelhoch=("cloud_cover_mid", "mean"),
        wolken_hoch=("cloud_cover_high", "mean"),
        wolken_streuung=("cloud_cover", "std"),
        sicht_mittel=("visibility", "mean"),
        sicht_min=("visibility", "min"),
        sonnen_sekunden=("sunshine_duration", "sum"),
        staub_max=("dust", "max"),
        staub_mittel=("dust", "mean"),
        pm10_mittel=("pm10", "mean"),
        aerosol_mittel=("aerosol_od", "mean"),
        stunden=("timestamp", "count"),
    ).reset_index()

    taeglich["gti_kwh_m2"] = taeglich["gti_wh_m2"] / 1000.0
    taeglich["sonnenstunden"] = taeglich["sonnen_sekunden"] / 3600.0
    taeglich = taeglich.drop(columns=["gti_wh_m2", "sonnen_sekunden"])

    vollstaendig = taeglich["stunden"] >= MIN_STUNDEN
    if (~vollstaendig).any():
        logger.info("Merkmalsbau: %s unvollstaendige Tage verworfen",
                    int((~vollstaendig).sum()))
    return taeglich[vollstaendig].drop(columns=["stunden"])


def baue_merkmalsmatrix(session: Session, plant_id: int = 1) -> pd.DataFrame:
    produktion = _lade_produktion(session, plant_id)
    stunden = _lade_stundenwerte(session, plant_id)
    if produktion.empty or stunden.empty:
        raise ValueError("Produktions- oder Wetterdaten fehlen")

    frame = produktion.merge(verdichte_auf_tage(stunden), on="date", how="inner")

    # zweite Sicherung, exakte Nullen lässt schon der Hoymiles-Adapter aus
    ausfall = frame[ZIELGROESSE] <= AUSFALL_SCHWELLE_KWH
    if ausfall.any():
        logger.info("Merkmalsbau: %s Ausfalltage verworfen, %s bis %s",
                    int(ausfall.sum()),
                    frame.loc[ausfall, "date"].min(),
                    frame.loc[ausfall, "date"].max())
        frame = frame[~ausfall]

    breite = load_plant_config().location.latitude
    sonne = sonnenstand_merkmale(pd.Series(pd.to_datetime(frame["date"])), breite)
    frame = pd.concat([frame.reset_index(drop=True),
                       sonne.reset_index(drop=True)], axis=1)

    frame = frame.sort_values("date").reset_index(drop=True)
    logger.info("Merkmalsmatrix: %s Tage, %s Merkmale", len(frame), len(ALLE_MERKMALE))
    return frame


def bestimme_wetterlage(zeile: pd.Series, staub_schwelle: float) -> str:
    if pd.notna(zeile.get("staub_max")) and zeile["staub_max"] >= staub_schwelle:
        return "saharastaub"
    if pd.notna(zeile.get("wolken_tief")) and zeile["wolken_tief"] >= 75:
        sicht = zeile.get("sicht_mittel")
        if pd.notna(sicht):
            if sicht <= 8:
                return "hochnebel"
        elif pd.notna(zeile.get("sonnenstunden")) and zeile["sonnenstunden"] <= 0.5:
            return "hochnebel"
    if pd.notna(zeile.get("wolken_mittel")):
        if zeile["wolken_mittel"] <= 25:
            return "klar"
        if zeile["wolken_mittel"] >= 75:
            return "bedeckt"
        if pd.notna(zeile.get("wolken_streuung")) and zeile["wolken_streuung"] >= 30:
            return "wechselhaft"
    return "gemischt"


def ergaenze_wetterlagen(frame: pd.DataFrame) -> pd.DataFrame:
    schwelle = float(np.nanpercentile(frame["staub_max"].astype(float), 90))
    ergebnis = frame.copy()
    ergebnis["wetterlage"] = ergebnis.apply(
        bestimme_wetterlage, axis=1, staub_schwelle=schwelle
    )
    ergebnis.attrs["staub_schwelle"] = schwelle
    return ergebnis
