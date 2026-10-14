import logging

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.sonnenstand import sonnenstand_merkmale
from app.config import load_plant_config
from app.models import DailyFact, HourlyForecast, HourlyWeather
from app.standorte import ist_uebergang, standortnummern

logger = logging.getLogger(__name__)

MERKMALSGRUPPEN: dict[str, list[str]] = {
    "wetter": [
        "gti_kwh_m2", "temp_mittel", "temp_max",
        "wolken_mittel", "wolken_tief", "wolken_mittelhoch", "wolken_hoch",
        "wolken_streuung", "sonnenstunden",
    ],
    "luftqualitaet": ["staub_max", "staub_mittel", "pm10_mittel", "aerosol_mittel"],
    "sonnenstand": ["tageslaenge_h", "mittagshoehe_grad", "jahrestag_sin", "jahrestag_cos"],
    "satellit": ["gti_satellit_kwh_m2"],
}

GRUPPENNAMEN = {
    "wetter": "Wetter (ICON-D2-Analyse)",
    "luftqualitaet": "Luftqualität und Saharastaub",
    "sonnenstand": "Sonnenstand",
    "satellit": "Satellit (SARAH-3)",
}

# kein Datenquellenmerkmal, deshalb ausserhalb der Ablation
ANLAGE = ["standort"]

ALLE_MERKMALE = [s for spalten in MERKMALSGRUPPEN.values() for s in spalten] + ANLAGE

# die archivierten Vorhersagen enthalten keine Wolkenschichten
VORHERSAGE_MERKMALE = [
    "gti_kwh_m2", "temp_mittel", "temp_max", "wolken_mittel", "wolken_streuung",
    "sonnenstunden", *MERKMALSGRUPPEN["sonnenstand"], *ANLAGE,
]

ZIELGROESSE = "production_kwh"

STUNDENSPALTEN = [
    "gti", "gti_satellit", "temperature", "cloud_cover", "cloud_cover_low",
    "cloud_cover_mid", "cloud_cover_high", "visibility", "sunshine_duration",
    "dust", "pm10", "aerosol_od",
]

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
    spalten = [getattr(HourlyWeather, s) for s in STUNDENSPALTEN]
    zeilen = session.execute(
        select(HourlyWeather.timestamp, *spalten)
        .where(HourlyWeather.plant_id == plant_id)
        .order_by(HourlyWeather.timestamp)
    ).all()
    return pd.DataFrame(zeilen, columns=["timestamp", *STUNDENSPALTEN])


def lade_stundenvorhersage(session: Session, plant_id: int, vorlauf: int) -> pd.DataFrame:
    zeilen = session.execute(
        select(HourlyForecast.timestamp, HourlyForecast.gti, HourlyForecast.temperature,
               HourlyForecast.cloud_cover, HourlyForecast.sunshine_duration)
        .where(HourlyForecast.plant_id == plant_id, HourlyForecast.vorlauf == vorlauf)
        .order_by(HourlyForecast.timestamp)
    ).all()
    return pd.DataFrame(zeilen, columns=[
        "timestamp", "gti", "temperature", "cloud_cover", "sunshine_duration",
    ])


def verdichte_auf_tage(stunden: pd.DataFrame) -> pd.DataFrame:
    """Stundenwerte zu Tagesmerkmalen, gleich für Rückblick, Vorhersagearchiv und Live-Vorhersage."""
    frame = stunden.reindex(columns=["timestamp", *STUNDENSPALTEN]).copy()
    for spalte in STUNDENSPALTEN:
        frame[spalte] = pd.to_numeric(frame[spalte], errors="coerce")
    zeit = pd.to_datetime(frame["timestamp"], utc=True)
    frame["date"] = zeit.dt.tz_convert("Europe/Berlin").dt.date

    taeglich = frame.groupby("date").agg(
        gti_wh_m2=("gti", "sum"),
        satellit_wh_m2=("gti_satellit", lambda werte: werte.sum(min_count=MIN_STUNDEN)),
        temp_mittel=("temperature", "mean"),
        temp_max=("temperature", "max"),
        wolken_mittel=("cloud_cover", "mean"),
        wolken_tief=("cloud_cover_low", "mean"),
        wolken_mittelhoch=("cloud_cover_mid", "mean"),
        wolken_hoch=("cloud_cover_high", "mean"),
        wolken_streuung=("cloud_cover", "std"),
        sicht_m=("visibility", "mean"),
        sonnen_sekunden=("sunshine_duration", "sum"),
        staub_max=("dust", "max"),
        staub_mittel=("dust", "mean"),
        pm10_mittel=("pm10", "mean"),
        aerosol_mittel=("aerosol_od", "mean"),
        stunden=("gti", "count"),
    ).reset_index()

    taeglich["gti_kwh_m2"] = taeglich["gti_wh_m2"] / 1000.0
    taeglich["gti_satellit_kwh_m2"] = taeglich["satellit_wh_m2"] / 1000.0
    taeglich["sonnenstunden"] = taeglich["sonnen_sekunden"] / 3600.0
    taeglich["sicht_km"] = taeglich["sicht_m"] / 1000.0
    taeglich = taeglich.drop(columns=["gti_wh_m2", "satellit_wh_m2", "sonnen_sekunden", "sicht_m"])

    vollstaendig = taeglich["stunden"] >= MIN_STUNDEN
    if (~vollstaendig).any():
        logger.info("Merkmalsbau: %s unvollstaendige Tage verworfen",
                    int((~vollstaendig).sum()))
    return taeglich[vollstaendig].drop(columns=["stunden"]).reset_index(drop=True)


def ergaenze_anlage(frame: pd.DataFrame) -> pd.DataFrame:
    """Sonnenstand und Standortnummer je Tag, aus Datum und Konfiguration berechnet."""
    plant = load_plant_config()
    tage = pd.Series(pd.to_datetime(frame["date"]))
    sonne = sonnenstand_merkmale(tage, plant.location.latitude)
    ergebnis = pd.concat([frame.reset_index(drop=True), sonne.reset_index(drop=True)], axis=1)
    ergebnis["standort"] = standortnummern(plant, ergebnis["date"]).to_numpy()
    return ergebnis


def _zusammenfuehren(produktion: pd.DataFrame, taeglich: pd.DataFrame) -> pd.DataFrame:
    frame = produktion.merge(taeglich, on="date", how="inner")

    # zweite Sicherung, exakte Nullen lässt schon der Hoymiles-Adapter aus
    ausfall = frame[ZIELGROESSE] <= AUSFALL_SCHWELLE_KWH
    plant = load_plant_config()
    uebergang = frame["date"].map(lambda t: ist_uebergang(plant, t)).astype(bool)
    if ausfall.any() or uebergang.any():
        logger.info("Merkmalsbau: %s Ausfalltage und %s Tage der Übergangszeit verworfen",
                    int(ausfall.sum()), int(uebergang.sum()))
    frame = frame[~ausfall & ~uebergang]

    frame = ergaenze_anlage(frame).sort_values("date").reset_index(drop=True)
    frame.attrs.update(ausfalltage=int(ausfall.sum()), uebergangstage=int(uebergang.sum()))
    return frame


def baue_merkmalsmatrix(session: Session, plant_id: int = 1) -> pd.DataFrame:
    produktion = _lade_produktion(session, plant_id)
    stunden = _lade_stundenwerte(session, plant_id)
    if produktion.empty or stunden.empty:
        raise ValueError("Produktions- oder Wetterdaten fehlen")

    frame = _zusammenfuehren(produktion, verdichte_auf_tage(stunden))
    logger.info("Merkmalsmatrix Rückblick: %s Tage, %s Merkmale", len(frame), len(ALLE_MERKMALE))
    return frame


def baue_vorhersagematrix(session: Session, plant_id: int = 1, vorlauf: int = 1) -> pd.DataFrame:
    """Dieselben Tage, aber mit dem Wetter, das vorlauf Tage vorher vorhergesagt war."""
    produktion = _lade_produktion(session, plant_id)
    stunden = lade_stundenvorhersage(session, plant_id, vorlauf)
    if produktion.empty or stunden.empty:
        raise ValueError("Produktionsdaten oder archivierte Vorhersagen fehlen")

    frame = _zusammenfuehren(produktion, verdichte_auf_tage(stunden))
    logger.info("Merkmalsmatrix Vorhersage, Vorlauf %s: %s Tage", vorlauf, len(frame))
    return frame


def bestimme_wetterlage(zeile: pd.Series, staub_schwelle: float) -> str:
    if pd.notna(zeile.get("staub_max")) and zeile["staub_max"] >= staub_schwelle:
        return "saharastaub"
    if pd.notna(zeile.get("wolken_tief")) and zeile["wolken_tief"] >= 75:
        sicht = zeile.get("sicht_km")
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
    staub = frame["staub_max"].astype(float)
    schwelle = float(np.nanpercentile(staub, 90)) if staub.notna().any() else float("inf")
    ergebnis = frame.copy()
    ergebnis["wetterlage"] = ergebnis.apply(
        bestimme_wetterlage, axis=1, staub_schwelle=schwelle
    )
    ergebnis.attrs["staub_schwelle"] = schwelle
    return ergebnis
