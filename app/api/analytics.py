import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.analytics.artefakte import lade_ergebnisse
from app.analytics.prognose import guete, pflege_prognosearchiv, prognostiziere, verlauf
from app.analytics.training import trainiere_und_bewerte
from app.database import SessionLocal
from app.pipeline.ingestion import _current_plant_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["Analyse"])

_sperre = threading.Lock()
_lauf = {"laeuft": False, "gestartet": None, "beendet": None, "fehler": None}


def _plant_id() -> int:
    with SessionLocal() as session:
        return _current_plant_id(session)


def _analyse_im_hintergrund() -> None:
    try:
        with SessionLocal() as session:
            trainiere_und_bewerte(session, _current_plant_id(session))
        _lauf["fehler"] = None
    except Exception as fehler:
        logger.exception("Analyselauf fehlgeschlagen")
        _lauf["fehler"] = str(fehler)[:500]
    finally:
        _lauf.update(laeuft=False, beendet=datetime.now(timezone.utc).isoformat())
        _sperre.release()


@router.get("/status")
def status() -> dict:
    """Sagt, ob gerade ein Analyselauf rechnet und wann der letzte fertig wurde."""
    ergebnisse = lade_ergebnisse()
    return {
        "lauf": _lauf,
        "trainiert": ergebnisse is not None,
        "trainiert_am": ergebnisse["trainiert_am"] if ergebnisse else None,
        "tage": ergebnisse["daten"]["tage"] if ergebnisse else None,
        "eingesetzt": ergebnisse["eingesetzt"] if ergebnisse else None,
    }


@router.post("/train", status_code=202)
def train() -> dict:
    """Startet Modellvergleich, Ablation und Importance im Hintergrund, Dauer einige Minuten."""
    if not _sperre.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ein Analyselauf läuft bereits")
    _lauf.update(laeuft=True, gestartet=datetime.now(timezone.utc).isoformat(), fehler=None)
    threading.Thread(target=_analyse_im_hintergrund, daemon=True).start()
    return {"gestartet": True}


@router.get("/ergebnisse")
def ergebnisse() -> dict:
    """Ergebnisse des letzten Analyselaufs, die Zahlenquelle für Kapitel 6."""
    daten = lade_ergebnisse()
    if daten is None:
        raise HTTPException(status_code=404, detail="Noch kein Analyselauf durchgeführt")
    return daten


@router.get("/prognose")
def prognose() -> dict:
    """Ertragsprognose für heute und die nächsten sechs Tage mit Spanne."""
    try:
        return prognostiziere(_plant_id())
    except Exception as fehler:
        logger.exception("Prognose fehlgeschlagen")
        raise HTTPException(status_code=502, detail=f"Prognose fehlgeschlagen: {fehler}")


@router.get("/verlauf")
def prognoseverlauf(tage: int = 180) -> dict:
    """Je Tag Messung und festgeschriebene Prognosen mit Vorlauf 1 bis 6."""
    return verlauf(_plant_id(), max(14, min(tage, 500)))


@router.get("/guete")
def prognoseguete() -> dict:
    """Fehler nach Vorlauf und Jahreszeit, Trefferquote der Spanne, Protokoll."""
    return guete(_plant_id())


@router.post("/archiv")
def archiv_pflegen() -> dict:
    """Trägt fehlende Prognosen im Rückblick nach und schreibt ab 20 Uhr die heutige fest."""
    return pflege_prognosearchiv(_plant_id())
