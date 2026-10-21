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
from app.adapters.open_meteo_satellit import OpenMeteoSatellitAdapter
from app.adapters.open_meteo_vorhersage import OpenMeteoVorhersagearchivAdapter
from app.adapters.open_meteo_weather import OpenMeteoWeatherAdapter
from app.config import load_hoymiles_auth, load_plant_config, load_sources_config
from app.database import SessionLocal, engine
from app.models import DailyFact, HourlyForecast, HourlyWeather, PipelineRun, PlantConfig
from app.pipeline.transformation import (
    LOCAL_TZ,
    aggregate_daily,
    find_production_gaps,
    finde_wetterluecken,
    lade_tageslage,
)
from app.pipeline.util import to_records

logger = logging.getLogger(__name__)

# Quelle: (Adapter, Zieltabelle, Schlüsselspalten)
ADAPTERS = {
    "open_meteo_weather": (OpenMeteoWeatherAdapter, HourlyWeather, ("plant_id", "timestamp")),
    "open_meteo_air": (OpenMeteoAirAdapter, HourlyWeather, ("plant_id", "timestamp")),
    "open_meteo_satellit": (OpenMeteoSatellitAdapter, HourlyWeather, ("plant_id", "timestamp")),
    "open_meteo_vorhersagearchiv": (
        OpenMeteoVorhersagearchivAdapter, HourlyForecast, ("plant_id", "timestamp", "vorlauf"),
    ),
}

# Obergrenze je Lauf. Der Rest kommt beim nächsten Durchlauf dran.
BACKFILL_MAX_BLOECKE = 12

# Postgres erlaubt höchstens 65535 Parameter je Anweisung
ZEILEN_JE_BLOCK = 4000


def _current_plant_id(session) -> int:
    """Liefert die id der konfigurierten Anlage."""
    settings = load_plant_config()
    return session.execute(
        select(PlantConfig).where(PlantConfig.name == settings.name)
    ).scalar_one().id


def ingest_source(
    name: str, start: date | None = None, end: date | None = None
) -> dict:
    """Holt die Daten einer Open-Meteo-Quelle und schreibt sie in ihre Tabelle."""
    if name not in ADAPTERS:
        return {"status": "fehler", "grund": f"Unbekannte Quelle: {name}"}

    adapter_klasse, tabelle, schluessel = ADAPTERS[name]
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

        adapter = adapter_klasse(plant_settings, source, plant_id)

        try:
            frame = adapter.fetch(start, end)
        except (SchemaError, SchemaErrors) as fehler:
            logger.error("Validierung fehlgeschlagen für %s: %s", name, fehler)
            return {"status": "ungueltig", "quelle": name,
                    "zeitraum": f"{start} bis {end}",
                    "grund": str(fehler).splitlines()[0][:300]}

        records = to_records(frame)
        update_columns = [s for s in frame.columns if s not in schluessel]

        for beginn in range(0, len(records), ZEILEN_JE_BLOCK):
            statement = insert(tabelle).values(records[beginn:beginn + ZEILEN_JE_BLOCK])
            statement = statement.on_conflict_do_update(
                index_elements=list(schluessel),
                set_={spalte: statement.excluded[spalte] for spalte in update_columns},
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
    """Ruft alle konfigurierten Open-Meteo-Quellen für denselben Zeitraum ab."""
    return [ingest_source(name, start, end) for name in ADAPTERS]


def lade_vorhersagelage(plant_id: int) -> pd.DataFrame:
    """Je Tag die Produktion und die Zahl archivierter Vorhersagestunden mit Vorlauf 1."""
    stunden = pd.read_sql(
        select(HourlyForecast.timestamp)
        .where(HourlyForecast.plant_id == plant_id, HourlyForecast.vorlauf == 1,
               HourlyForecast.gti.is_not(None)),
        engine,
    )
    tage = lade_tageslage(plant_id)[["date", "production_kwh"]]
    if stunden.empty:
        return tage.assign(hours=None)
    lokal = pd.to_datetime(stunden["timestamp"], utc=True).dt.tz_convert(LOCAL_TZ).dt.date
    zaehler = lokal.value_counts().rename("hours")
    return tage.merge(zaehler, left_on="date", right_index=True, how="left")


def _nachladen(bloecke: list[dict], quellen: list[str]) -> int:
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
        logger.info("Backfill %s bis %s, %s Tage, %s",
                    block["von"], block["bis"], block["tage"], ", ".join(quellen))
        for name in quellen:
            datensaetze += ingest_source(name, von, bis).get("datensaetze", 0)
    return datensaetze


def backfill_weather() -> dict:
    """Lädt Wetter und archivierte Vorhersagen für alle Tage im Messzeitraum nach, denen Stundenwerte fehlen."""
    with SessionLocal() as session:
        plant_id = _current_plant_id(session)

    wetter = finde_wetterluecken(lade_tageslage(plant_id))
    vorhersage = finde_wetterluecken(lade_vorhersagelage(plant_id))
    if not wetter and not vorhersage:
        return {"status": "ok", "bloecke": 0, "tage": 0, "datensaetze": 0}

    datensaetze = _nachladen(
        wetter, ["open_meteo_weather", "open_meteo_air", "open_meteo_satellit"]
    )
    datensaetze += _nachladen(vorhersage, ["open_meteo_vorhersagearchiv"])

    return {
        "status": "ok",
        "bloecke": len(wetter) + len(vorhersage),
        "tage": sum(block["tage"] for block in wetter + vorhersage),
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


def _pflege_prognosen(plant_id: int) -> dict:
    # erst hier importiert, die Analyse hängt selbst an der Pipeline
    from app.analytics.prognose import pflege_prognosearchiv

    try:
        return pflege_prognosearchiv(plant_id)
    except Exception as fehler:
        logger.exception("Prognosearchiv nicht aktualisiert")
        return {"status": "fehler", "grund": str(fehler)[:300]}


def run_pipeline(
    start: date | None = None,
    end: date | None = None,
    trigger: str = "manuell",
) -> dict:
    """Ruft alle Quellen ab, verdichtet auf Tageswerte und führt das Prognosearchiv fort."""
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
        prognosen = _pflege_prognosen(plant_id)

        ungueltig = [q["quelle"] for q in quellen if q["status"] == "ungueltig"]

        ergebnis = {
            "status": "teilweise" if ungueltig else "ok",
            "quellen": quellen,
            "backfill": nachgeladen,
            "aggregation": aggregation,
            "datenqualitaet": luecken,
            "prognosearchiv": prognosen,
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
