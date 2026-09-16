import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from pandera.errors import SchemaError, SchemaErrors
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.adapters.hoymiles_api import HoymilesApiAdapter
from app.adapters.hoymiles_csv import HoymilesEnergyAdapter
from app.adapters.open_meteo_air import OpenMeteoAirAdapter
from app.adapters.open_meteo_weather import OpenMeteoWeatherAdapter
from app.config import load_hoymiles_auth, load_plant_config, load_sources_config
from app.database import SessionLocal
from app.models import DailyFact, HourlyWeather, PipelineRun, PlantConfig
from app.pipeline.transformation import (
    aggregate_daily,
    find_production_gaps,
    finde_wetterluecken,
    lade_tageslage,
)
from app.pipeline.util import to_records

logger = logging.getLogger(__name__)

ADAPTERS = {
    "open_meteo_weather": OpenMeteoWeatherAdapter,
    "open_meteo_air": OpenMeteoAirAdapter,
}

KEY_COLUMNS = ("plant_id", "timestamp")

# Obergrenze je Lauf. Der Rest kommt beim nächsten Durchlauf dran.
BACKFILL_MAX_BLOECKE = 12


def _current_plant_id(session) -> int:
    """Liefert die id der konfigurierten Anlage."""
    settings = load_plant_config()
    return session.execute(
        select(PlantConfig).where(PlantConfig.name == settings.name)
    ).scalar_one().id


def ingest_source(
    name: str, start: date | None = None, end: date | None = None
) -> dict:
    """Holt die Daten einer Wetterquelle und schreibt sie nach hourly_weather."""
    if name not in ADAPTERS:
        return {"status": "fehler", "grund": f"Unbekannte Quelle: {name}"}

    plant_settings = load_plant_config()
    source = getattr(load_sources_config(), name)

    if not source.enabled:
        return {"status": "uebersprungen", "quelle": name,
                "grund": "Quelle ist deaktiviert"}

    if end is None:
        end = date.today()
    if start is None:
        start = end - timedelta(days=source.default_days_back)

    with SessionLocal() as session:
        plant_id = _current_plant_id(session)

        adapter = ADAPTERS[name](plant_settings, source, plant_id)

        try:
            frame = adapter.fetch(start, end)
        except (SchemaError, SchemaErrors) as fehler:
            logger.error("Validierung fehlgeschlagen für %s: %s", name, fehler)
            return {"status": "ungueltig", "quelle": name,
                    "zeitraum": f"{start} bis {end}",
                    "grund": str(fehler).splitlines()[0][:300]}

        records = to_records(frame)

        update_columns = [
            spalte for spalte in frame.columns if spalte not in KEY_COLUMNS
        ]

        statement = insert(HourlyWeather).values(records)
        statement = statement.on_conflict_do_update(
            index_elements=list(KEY_COLUMNS),
            set_={
                spalte: statement.excluded[spalte] for spalte in update_columns
            },
        )
        session.execute(statement)
        session.commit()

    return {
        "status": "ok",
        "quelle": name,
        "zeitraum": f"{start} bis {end}",
        "datensaetze": len(records),
        "spalten": update_columns,
    }


def ingest_all(start: date | None = None, end: date | None = None) -> list[dict]:
    """Ruft alle konfigurierten Wetterquellen für denselben Zeitraum ab."""
    return [ingest_source(name, start, end) for name in ADAPTERS]


def backfill_weather() -> dict:
    """Lädt Wetterdaten für Tage nach, an denen nur Produktion vorliegt."""
    with SessionLocal() as session:
        plant_id = _current_plant_id(session)

    bloecke = finde_wetterluecken(lade_tageslage(plant_id))
    if not bloecke:
        return {"status": "ok", "bloecke": 0, "tage": 0, "datensaetze": 0}

    if len(bloecke) > BACKFILL_MAX_BLOECKE:
        logger.warning(
            "%s Lückenblöcke gefunden, davon werden %s nachgeladen",
            len(bloecke), BACKFILL_MAX_BLOECKE,
        )
        bloecke = bloecke[:BACKFILL_MAX_BLOECKE]

    datensaetze = 0
    for block in bloecke:
        von = block["von"] - timedelta(days=1)
        bis = min(block["bis"] + timedelta(days=1), date.today())

        logger.info("Backfill %s bis %s, %s Tage",
                    block["von"], block["bis"], block["tage"])
        for ergebnis in ingest_all(von, bis):
            datensaetze += ergebnis.get("datensaetze", 0)

    return {
        "status": "ok",
        "bloecke": len(bloecke),
        "tage": sum(block["tage"] for block in bloecke),
        "datensaetze": datensaetze,
    }


def _produktion_startdatum(plant_id: int, tage_zurueck: int) -> date:
    with SessionLocal() as session:
        letzter = session.execute(
            select(func.max(DailyFact.date))
            .where(DailyFact.plant_id == plant_id)
            .where(DailyFact.production_kwh.is_not(None))
        ).scalar_one()

    if letzter is None:
        seit = load_plant_config().installation_date
        logger.info("Keine Produktionsdaten vorhanden, hole ab %s", seit)
        return seit

    return letzter - timedelta(days=tage_zurueck)


def ingest_production(
    start: date | None = None, end: date | None = None
) -> dict:
    """Holt die Tagesproduktion aus der Hoymiles-Cloud nach daily_facts.

    Der laufende Tag wird ausgelassen, sein Ertrag wäre nur ein Zwischenstand.
    """
    source = load_sources_config().hoymiles_api

    if not source.enabled:
        return {"status": "uebersprungen", "quelle": "hoymiles_api",
                "grund": "Quelle ist deaktiviert"}

    zugang = load_hoymiles_auth()
    if zugang is None:
        return {"status": "uebersprungen", "quelle": "hoymiles_api",
                "grund": "config/hoymiles_auth.yaml fehlt"}

    gestern = date.today() - timedelta(days=1)
    if end is None:
        end = gestern
    else:
        end = min(end, gestern)

    with SessionLocal() as session:
        plant_id = _current_plant_id(session)

    if start is None:
        start = _produktion_startdatum(plant_id, source.default_days_back)

    if start > end:
        return {"status": "uebersprungen", "quelle": "hoymiles_api",
                "grund": "Kein abgeschlossener Tag im Zeitraum"}

    with SessionLocal() as session:
        adapter = HoymilesApiAdapter(
            load_plant_config(), source, plant_id, zugang
        )

        try:
            frame = adapter.fetch(start, end)
        except (SchemaError, SchemaErrors) as fehler:
            logger.error("Validierung fehlgeschlagen für hoymiles_api: %s", fehler)
            return {"status": "ungueltig", "quelle": "hoymiles_api",
                    "grund": str(fehler).splitlines()[0][:300]}

        if frame.empty:
            return {"status": "ok", "quelle": "hoymiles_api", "datensaetze": 0}

        records = to_records(frame)
        statement = insert(DailyFact).values(records)
        statement = statement.on_conflict_do_update(
            index_elements=["plant_id", "date"],
            set_={"production_kwh": statement.excluded.production_kwh},
        )
        session.execute(statement)
        session.commit()

    return {
        "status": "ok",
        "quelle": "hoymiles_api",
        "zeitraum": f"{start} bis {end}",
        "datensaetze": len(records),
    }


def hoymiles_realtime() -> dict:
    """Liest die aktuelle Leistung direkt aus der Hoymiles-Cloud.
    """
    zugang = load_hoymiles_auth()
    if zugang is None:
        return {"status": "uebersprungen", "quelle": "hoymiles_api",
                "grund": "config/hoymiles_auth.yaml fehlt"}

    with SessionLocal() as session:
        plant_id = _current_plant_id(session)

    adapter = HoymilesApiAdapter(
        load_plant_config(), load_sources_config().hoymiles_api, plant_id, zugang
    )
    werte = adapter.realtime()

    if werte is None:
        return {"status": "fehler", "quelle": "hoymiles_api",
                "grund": "Keine verwertbare Antwort der Cloud"}

    return {"status": "ok", "quelle": "hoymiles_api", **werte}


def import_energy_report(path: Path) -> dict:
    """Liest einen Hoymiles-Energy-Report ein und schreibt ihn nach daily_facts."""
    with SessionLocal() as session:
        plant_id = _current_plant_id(session)

        adapter = HoymilesEnergyAdapter()
        frame = adapter.parse(path, plant_id)
        records = to_records(frame)

        statement = insert(DailyFact).values(records)
        statement = statement.on_conflict_do_update(
            index_elements=["plant_id", "date"],
            set_={"production_kwh": statement.excluded.production_kwh},
        )
        session.execute(statement)
        session.commit()

    kalender = pd.date_range(frame["date"].min(), frame["date"].max(), freq="D")
    fehlend = kalender.difference(frame["date"])

    return {
        "status": "ok",
        "quelle": adapter.name,
        "datei": path.name,
        "datensaetze": len(records),
        "zeitraum": f"{frame['date'].min().date()} bis {frame['date'].max().date()}",
        "kalendertage": len(kalender),
        "fehlende_tage": len(fehlend),
    }


def run_pipeline(
    start: date | None = None,
    end: date | None = None,
    trigger: str = "manuell",
) -> dict:
    """Ruft alle Quellen ab und verdichtet anschliessend auf Tageswerte."""
    lauf = PipelineRun(
        started_at=datetime.now(timezone.utc),
        trigger=trigger,
        status="laeuft",
    )
    with SessionLocal() as session:
        session.add(lauf)
        session.commit()
        lauf_id = lauf.id

    try:
        quellen = ingest_all(start, end)
        produktion = ingest_production(start, end)
        quellen.append(produktion)

        nachgeladen = backfill_weather()

        with SessionLocal() as session:
            plant_id = _current_plant_id(session)

        aggregation = aggregate_daily(plant_id)
        luecken = find_production_gaps(plant_id)

        ungueltig = [q["quelle"] for q in quellen if q["status"] == "ungueltig"]

        ergebnis = {
            "status": "teilweise" if ungueltig else "ok",
            "quellen": quellen,
            "backfill": nachgeladen,
            "aggregation": aggregation,
            "datenqualitaet": luecken,
        }
        _lauf_abschliessen(
            lauf_id,
            status=ergebnis["status"],
            records=sum(q.get("datensaetze", 0) for q in quellen)
            + nachgeladen["datensaetze"],
            days=aggregation.get("geschriebene_tage"),
            error=f"Ungültige Daten: {', '.join(ungueltig)}" if ungueltig else None,
        )
        return ergebnis

    except Exception as fehler:
        logger.exception("Pipeline-Lauf fehlgeschlagen")
        _lauf_abschliessen(lauf_id, status="fehler", error=str(fehler)[:2000])
        raise


def _lauf_abschliessen(
    lauf_id: int,
    status: str,
    records: int | None = None,
    days: int | None = None,
    error: str | None = None,
) -> None:
    with SessionLocal() as session:
        lauf = session.get(PipelineRun, lauf_id)
        lauf.finished_at = datetime.now(timezone.utc)
        lauf.status = status
        lauf.records = records
        lauf.days = days
        lauf.error = error
        session.commit()
