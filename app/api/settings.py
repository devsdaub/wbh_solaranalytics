from fastapi import APIRouter, Form
from fastapi.responses import RedirectResponse

from app.config import (
    load_scheduler_config,
    load_sources_config,
    save_scheduler_config,
    save_sources_config,
)
from app.pipeline.ingestion import backfill_weather, run_pipeline
from app.pipeline.scheduler import apply_config

router = APIRouter(prefix="/settings", tags=["Einstellungen"])


@router.post("/scheduler")
def update_scheduler(
    interval_minutes: int = Form(...),
    enabled: bool = Form(False),
) -> RedirectResponse:
    """Speichert die Scheduler-Konfiguration und übernimmt sie sofort."""
    settings = load_scheduler_config()
    settings.enabled = enabled
    settings.jobs["pipeline"].interval_minutes = interval_minutes
    settings.jobs["pipeline"].enabled = enabled
    save_scheduler_config(settings)

    apply_config()

    return RedirectResponse("/settings?gespeichert=scheduler", status_code=303)


@router.post("/sources")
def update_sources(
    open_meteo_weather: bool = Form(False),
    open_meteo_air: bool = Form(False),
    hoymiles_api: bool = Form(False),
) -> RedirectResponse:
    """Schaltet einzelne Datenquellen an oder ab."""
    settings = load_sources_config()
    settings.open_meteo_weather.enabled = open_meteo_weather
    settings.open_meteo_air.enabled = open_meteo_air
    settings.hoymiles_api.enabled = hoymiles_api
    save_sources_config(settings)

    return RedirectResponse("/settings?gespeichert=quellen", status_code=303)


@router.post("/run")
def trigger_run_from_form() -> RedirectResponse:
    """Löst einen Pipeline-Lauf aus und kehrt zur Settings-Seite zurück."""
    try:
        ergebnis = run_pipeline(trigger="manuell")
    except Exception:
        return RedirectResponse("/settings?gespeichert=fehler", status_code=303)

    tage = ergebnis["aggregation"].get("geschriebene_tage", 0)
    return RedirectResponse(f"/settings?gespeichert=lauf&tage={tage}", status_code=303)


@router.post("/backfill")
def trigger_backfill_from_form() -> RedirectResponse:
    """Lädt fehlende Wetterdaten nach und kehrt zur Settings-Seite zurück."""
    try:
        ergebnis = backfill_weather()
    except Exception:
        return RedirectResponse("/settings?gespeichert=fehler", status_code=303)

    return RedirectResponse(
        f"/settings?gespeichert=backfill&tage={ergebnis['tage']}", status_code=303
    )
