import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text

from app.config import SchedulerSettings, load_scheduler_config
from app.database import engine
from app.pipeline.ingestion import run_pipeline

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC")

JOB_ID = "pipeline"
ANALYSE_ID = "analyse"

# eine Woche, so alt darf der letzte Analyselauf höchstens werden
ANALYSE_INTERVALL_MINUTEN = 7 * 24 * 60
# stündlich prüfen statt fest alle sieben Tage, damit Neustarts des Rechners den Lauf nicht verschieben
PRUEFTAKT_MINUTEN = 60

# frei gewählte, projektweit eindeutige Kennung der Advisory Lock
LOCK_KEY = 4711

_lock_connection = None


def _sperre_erhalten() -> bool:
    """Versucht, die projektweite Scheduler-Sperre zu belegen."""
    global _lock_connection

    verbindung = engine.connect()
    erhalten = verbindung.execute(
        text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}
    ).scalar_one()

    if erhalten:
        _lock_connection = verbindung
    else:
        verbindung.close()
    return erhalten


def _pipeline_job() -> None:
    try:
        run_pipeline(trigger="scheduler")
    except Exception:
        logger.exception("Geplanter Pipeline-Lauf fehlgeschlagen")


def analyse_faellig(trainiert_am: str | None, intervall_minuten: int) -> bool:
    if trainiert_am is None:
        return True
    alter = datetime.now(timezone.utc) - datetime.fromisoformat(trainiert_am)
    return alter >= timedelta(minutes=intervall_minuten)


def _analyse_job() -> None:
    from app.analytics.artefakte import lade_ergebnisse
    from app.api.analytics import starte_analyse

    job = load_scheduler_config().jobs.get("analyse")
    if job is None or not job.enabled:
        return
    ergebnisse = lade_ergebnisse()
    if not analyse_faellig(ergebnisse["trainiert_am"] if ergebnisse else None, job.interval_minutes):
        return
    if starte_analyse():
        logger.info("Wöchentlicher Analyselauf gestartet")


def _plane_analyse(settings: SchedulerSettings) -> None:
    """Legt die stündliche Prüfung auf eine fällige Analyse an oder entfernt sie."""
    job = settings.jobs.get("analyse")
    if job is not None and job.enabled:
        if scheduler.get_job(ANALYSE_ID) is None:
            scheduler.add_job(
                _analyse_job,
                trigger="interval",
                minutes=PRUEFTAKT_MINUTEN,
                id=ANALYSE_ID,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                next_run_time=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
            logger.info("Wöchentlicher Analyselauf eingeplant")
    elif scheduler.get_job(ANALYSE_ID) is not None:
        scheduler.remove_job(ANALYSE_ID)
        logger.info("Wöchentlicher Analyselauf abgeschaltet")


def start_scheduler() -> None:
    """Startet den Hintergrund-Scheduler gemäss scheduler.yaml."""
    settings = load_scheduler_config()

    if not settings.enabled:
        logger.info("Scheduler ist deaktiviert")
        return

    job = settings.jobs["pipeline"]
    if not job.enabled:
        logger.info("Pipeline-Auftrag ist deaktiviert")
        return

    if not _sperre_erhalten():
        logger.info("Scheduler läuft bereits in einem anderen Prozess")
        return

    scheduler.add_job(
        _pipeline_job,
        trigger="interval",
        minutes=job.interval_minutes,
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    _plane_analyse(settings)
    scheduler.start()
    logger.info("Scheduler gestartet, Intervall %s Minuten", job.interval_minutes)


def stop_scheduler() -> None:
    global _lock_connection, scheduler

    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler gestoppt")
        scheduler = BackgroundScheduler(timezone="UTC")

    if _lock_connection is not None:
        _lock_connection.close()
        _lock_connection = None


def apply_config() -> dict:
    """Bringt den laufenden Scheduler auf den Stand der Konfiguration."""
    settings = load_scheduler_config()
    job = settings.jobs["pipeline"]
    soll_laufen = settings.enabled and job.enabled

    if not soll_laufen:
        stop_scheduler()
        return {"laeuft": False, "grund": "deaktiviert"}

    if not scheduler.running:
        start_scheduler()
        return {"laeuft": scheduler.running, "grund": "gestartet"}

    if scheduler.get_job(JOB_ID):
        scheduler.reschedule_job(
            JOB_ID, trigger="interval", minutes=job.interval_minutes
        )
        logger.info("Intervall geändert auf %s Minuten", job.interval_minutes)
    _plane_analyse(settings)

    return {"laeuft": True, "grund": "umgeplant"}


def scheduler_status() -> dict:
    """Liefert den aktuellen Zustand für die Anzeige."""
    job = scheduler.get_job(JOB_ID) if scheduler.running else None
    analyse = scheduler.get_job(ANALYSE_ID) if scheduler.running else None
    return {
        "laeuft": scheduler.running,
        "hat_sperre": _lock_connection is not None,
        "naechster_lauf": job.next_run_time.isoformat() if job else None,
        "analyse_eingeplant": analyse is not None,
    }
