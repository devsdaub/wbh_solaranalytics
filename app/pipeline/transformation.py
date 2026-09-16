import logging

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import load_plant_config
from app.database import SessionLocal, engine
from app.models import DailyFact, HourlyWeather
from app.pipeline.util import to_records

logger = logging.getLogger(__name__)

LOCAL_TZ = "Europe/Berlin"

# Ein vollständiger Tag hat 24 Stundenwerte, an der Zeitumstellung 23 oder 25.
MIN_STUNDEN = 23

DAILY_UPDATE_COLUMNS = (
    "gti_kwh",
    "avg_temperature",
    "avg_cloud_cover",
    "max_dust",
    "avg_pm10",
    "hours",
    "eq",
)


def aggregate_hourly(frame: pd.DataFrame, plant_id: int) -> pd.DataFrame:
    """Verdichtet Stundenwerte auf lokale Kalendertage."""
    if frame.empty:
        return pd.DataFrame(columns=["plant_id", "date", *DAILY_UPDATE_COLUMNS[:-1]])

    tage = frame["timestamp"].dt.tz_convert(LOCAL_TZ).dt.date

    taeglich = frame.assign(date=tage).groupby("date").agg(
        gti_kwh=("gti", lambda werte: werte.sum(min_count=1) / 1000.0),
        avg_temperature=("temperature", "mean"),
        avg_cloud_cover=("cloud_cover", "mean"),
        max_dust=("dust", "max"),
        avg_pm10=("pm10", "mean"),
        hours=("timestamp", "size"),
    ).reset_index()

    taeglich["avg_cloud_cover"] = taeglich["avg_cloud_cover"].round().astype("Int64")
    taeglich["plant_id"] = plant_id
    return taeglich


def berechne_eq(frame: pd.DataFrame, module_wp: int) -> pd.DataFrame:
    """Ergänzt den Effizienzquotienten aus Produktion und Einstrahlung."""
    produktion = pd.to_numeric(frame["production_kwh"], errors="coerce")
    nenner = pd.to_numeric(frame["gti_kwh"], errors="coerce") * (module_wp / 1000.0)
    frame["eq"] = produktion / nenner.where(nenner > 0)
    return frame


def zu_bloecken(tage: list) -> list[dict]:
    """Fasst aufeinanderfolgende Tage zu zusammenhängenden Blöcken zusammen."""
    if not tage:
        return []

    bloecke = []
    beginn = vorher = tage[0]
    for tag in tage[1:]:
        if (tag - vorher).days == 1:
            vorher = tag
        else:
            bloecke.append({"von": beginn, "bis": vorher,
                            "tage": (vorher - beginn).days + 1})
            beginn = vorher = tag

    bloecke.append({"von": beginn, "bis": vorher,
                    "tage": (vorher - beginn).days + 1})
    return bloecke


def _lade_stundenwerte(plant_id: int) -> pd.DataFrame:
    statement = select(
        HourlyWeather.timestamp,
        HourlyWeather.gti,
        HourlyWeather.temperature,
        HourlyWeather.cloud_cover,
        HourlyWeather.dust,
        HourlyWeather.pm10,
    ).where(HourlyWeather.plant_id == plant_id)
    return pd.read_sql(statement, engine)


def _lade_produktion(plant_id: int) -> pd.DataFrame:
    statement = select(DailyFact.date, DailyFact.production_kwh).where(
        DailyFact.plant_id == plant_id
    )
    return pd.read_sql(statement, engine)


def lade_tageslage(plant_id: int) -> pd.DataFrame:
    """Datum, Produktion und Zahl der Stundenwerte je Tag."""
    statement = select(
        DailyFact.date, DailyFact.production_kwh, DailyFact.hours
    ).where(DailyFact.plant_id == plant_id)
    return pd.read_sql(statement, engine)


def aggregate_daily(plant_id: int) -> dict:
    """Verdichtet die Stundenwerte zu Tageswerten in daily_facts."""
    module_wp = load_plant_config().panel.module_capacity_wp

    taeglich = aggregate_hourly(_lade_stundenwerte(plant_id), plant_id)
    if taeglich.empty:
        logger.warning("Keine Stundenwerte vorhanden, Aggregation übersprungen")
        return {"status": "uebersprungen", "geschriebene_tage": 0}

    taeglich = taeglich.merge(_lade_produktion(plant_id), on="date", how="left")
    taeglich = berechne_eq(taeglich, module_wp)
    taeglich = taeglich.drop(columns=["production_kwh"])

    with SessionLocal() as session:
        statement = insert(DailyFact).values(to_records(taeglich))
        statement = statement.on_conflict_do_update(
            index_elements=["plant_id", "date"],
            set_={s: statement.excluded[s] for s in DAILY_UPDATE_COLUMNS},
        )
        session.execute(statement)
        session.commit()

    logger.info("Tagesaggregation abgeschlossen: %s Tage", len(taeglich))
    return {"status": "ok", "geschriebene_tage": len(taeglich)}


def finde_luecken(frame: pd.DataFrame) -> list[dict]:
    """Fasst Tage ohne Produktionswert zu zusammenhängenden Blöcken zusammen."""
    gemessen = frame.dropna(subset=["production_kwh"])
    if gemessen.empty:
        return []

    kalender = pd.date_range(gemessen["date"].min(), gemessen["date"].max(), freq="D")
    vorhanden = set(gemessen["date"])

    return zu_bloecken([
        tag.date() for tag in kalender if tag.date() not in vorhanden
    ])


def finde_wetterluecken(frame: pd.DataFrame) -> list[dict]:
    """Tage mit Produktionswert, aber ohne vollständige Stundenwerte."""
    if frame.empty:
        return []

    unvollstaendig = frame["hours"].isna() | (frame["hours"] < MIN_STUNDEN)
    return zu_bloecken(
        sorted(frame[frame["production_kwh"].notna() & unvollstaendig]["date"])
    )


def find_production_gaps(plant_id: int) -> dict:
    """Findet Tage ohne Produktionswert innerhalb des Messzeitraums."""
    luecken = finde_luecken(_lade_produktion(plant_id))
    fehlend = sum(luecke["tage"] for luecke in luecken)

    if fehlend:
        logger.warning("Produktionslücken: %s Tage in %s Block/Blöcken",
                       fehlend, len(luecken))
    return {"fehlende_tage": fehlend, "luecken": luecken}


def find_weather_gaps(plant_id: int) -> dict:
    """Findet Tage mit Produktion, aber ohne vollständige Wetterdaten."""
    bloecke = finde_wetterluecken(lade_tageslage(plant_id))
    return {
        "fehlende_tage": sum(block["tage"] for block in bloecke),
        "luecken": bloecke,
    }
