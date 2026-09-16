from datetime import date

from fastapi import APIRouter
from sqlalchemy import select

from app.database import SessionLocal
from app.models import PipelineRun
from app.pipeline.ingestion import (
    _current_plant_id,
    backfill_weather,
    hoymiles_realtime,
    ingest_all,
    ingest_production,
    ingest_source,
    run_pipeline,
)
from app.pipeline.pruefung import qualitaetsbericht
from app.pipeline.scheduler import scheduler_status
from app.pipeline.transformation import (
    aggregate_daily,
    find_production_gaps,
    find_weather_gaps,
)
from app.pipeline.vergleich import vergleiche_produktion

router = APIRouter(prefix="/api", tags=["Pipeline"])


@router.post("/ingest/weather")
def trigger_weather_ingestion(
    start: date | None = None, end: date | None = None
) -> dict:
    """Stößt den Abruf der Wetterdaten an."""
    return ingest_source("open_meteo_weather", start, end)


@router.post("/ingest/air")
def trigger_air_ingestion(
    start: date | None = None, end: date | None = None
) -> dict:
    """Stößt den Abruf der Luftqualitätsdaten an."""
    return ingest_source("open_meteo_air", start, end)


@router.post("/ingest/all")
def trigger_full_ingestion(
    start: date | None = None, end: date | None = None
) -> list[dict]:
    """Ruft alle aktiven Quellen für denselben Zeitraum ab."""
    return ingest_all(start, end)


@router.post("/ingest/production")
def trigger_production_ingestion(
    start: date | None = None, end: date | None = None
) -> dict:
    """Holt die Tagesproduktion aus der Hoymiles-Cloud."""
    return ingest_production(start, end)


@router.post("/backfill/weather")
def trigger_backfill() -> dict:
    """Lädt Wetterdaten für Tage nach, an denen nur Produktion vorliegt."""
    return backfill_weather()


@router.get("/hoymiles/realtime")
def report_realtime() -> dict:
    """Aktuelle Leistung und Tagesertrag aus der Hoymiles-Cloud."""
    return hoymiles_realtime()


@router.post("/transform/daily")
def trigger_daily_aggregation() -> dict:
    """Verdichtet die Stundenwerte zu Tageswerten."""
    with SessionLocal() as session:
        plant_id = _current_plant_id(session)
    return aggregate_daily(plant_id)


@router.get("/quality/gaps")
def report_production_gaps() -> dict:
    """Meldet Lücken in den Produktionsdaten innerhalb des Messzeitraums."""
    with SessionLocal() as session:
        plant_id = _current_plant_id(session)
    return find_production_gaps(plant_id)


@router.get("/quality/weather-gaps")
def report_weather_gaps() -> dict:
    """Meldet Tage mit Produktion, aber ohne vollständige Wetterdaten."""
    with SessionLocal() as session:
        plant_id = _current_plant_id(session)
    return find_weather_gaps(plant_id)


@router.get("/quality/report")
def report_quality() -> dict:
    """Meldet fachliche Befunde und den Füllgrad der Spalten."""
    with SessionLocal() as session:
        plant_id = _current_plant_id(session)
    return qualitaetsbericht(plant_id)


@router.post("/pipeline/run")
def trigger_pipeline(start: date | None = None, end: date | None = None) -> dict:
    """Führt Datenabruf und Aggregation in einem Durchlauf aus."""
    return run_pipeline(start, end, trigger="manuell")


@router.get("/pipeline/status")
def pipeline_status() -> dict:
    """Liefert Scheduler-Zustand und den letzten Lauf."""
    with SessionLocal() as session:
        letzter = session.execute(
            select(PipelineRun).order_by(PipelineRun.id.desc()).limit(1)
        ).scalar_one_or_none()

    return {
        "scheduler": scheduler_status(),
        "letzter_lauf": {
            "gestartet": letzter.started_at,
            "beendet": letzter.finished_at,
            "ausloeser": letzter.trigger,
            "status": letzter.status,
            "datensaetze": letzter.records,
            "tage": letzter.days,
            "fehler": letzter.error,
        } if letzter else None,
    }


@router.get("/pipeline/runs")
def pipeline_runs(limit: int = 20) -> list[dict]:
    """Liefert die letzten Pipeline-Läufe."""
    with SessionLocal() as session:
        laeufe = session.execute(
            select(PipelineRun).order_by(PipelineRun.id.desc()).limit(limit)
        ).scalars().all()

    return [
        {
            "id": lauf.id,
            "gestartet": lauf.started_at,
            "beendet": lauf.finished_at,
            "ausloeser": lauf.trigger,
            "status": lauf.status,
            "datensaetze": lauf.records,
            "tage": lauf.days,
            "fehler": lauf.error,
        }
        for lauf in laeufe
    ]


@router.get("/quality/compare")
def compare_production(start: date, end: date) -> dict:
    """Vergleicht gespeicherte Produktionsdaten mit der Hoymiles-API."""
    with SessionLocal() as session:
        plant_id = _current_plant_id(session)
    return vergleiche_produktion(plant_id, start, end)
