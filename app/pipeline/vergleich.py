import logging
from datetime import date

import pandas as pd
from sqlalchemy import select

from app.adapters.hoymiles_api import HoymilesApiAdapter
from app.config import load_hoymiles_auth, load_plant_config, load_sources_config
from app.database import engine
from app.models import DailyFact

logger = logging.getLogger(__name__)

TOLERANZ_KWH = 0.02


def vergleiche_produktion(plant_id: int, start: date, end: date) -> dict:
    """Stellt die gespeicherten Tageswerte den Werten der Cloud-API gegenüber."""
    zugang = load_hoymiles_auth()
    if zugang is None:
        return {"status": "uebersprungen", "grund": "Zugangsdaten fehlen"}

    adapter = HoymilesApiAdapter(
        load_plant_config(), load_sources_config().hoymiles_api, plant_id, zugang
    )
    api = adapter.fetch(start, end)[["date", "production_kwh"]]

    statement = (
        select(DailyFact.date, DailyFact.production_kwh)
        .where(DailyFact.plant_id == plant_id)
        .where(DailyFact.date.between(start, end))
        .where(DailyFact.production_kwh.is_not(None))
    )
    gespeichert = pd.read_sql(statement, engine)
    gespeichert["date"] = pd.to_datetime(gespeichert["date"])

    zusammen = gespeichert.merge(
        api, on="date", how="outer", suffixes=("_db", "_api")
    )
    zusammen["differenz"] = (
        zusammen["production_kwh_db"] - zusammen["production_kwh_api"]
    ).abs()

    nur_db = zusammen["production_kwh_api"].isna().sum()
    nur_api = zusammen["production_kwh_db"].isna().sum()
    abweichend = zusammen[zusammen["differenz"] > TOLERANZ_KWH]

    if len(abweichend):
        logger.warning("Produktionsvergleich: %s Tage weichen ab", len(abweichend))

    return {
        "status": "ok",
        "zeitraum": f"{start} bis {end}",
        "verglichene_tage": int(zusammen["differenz"].notna().sum()),
        "nur_in_datenbank": int(nur_db),
        "nur_in_api": int(nur_api),
        "abweichende_tage": len(abweichend),
        "groesste_abweichung": round(float(zusammen["differenz"].max()), 3)
            if zusammen["differenz"].notna().any() else None,
        "abweichungen": [
            {
                "datum": zeile["date"].date().isoformat(),
                "datenbank": zeile["production_kwh_db"],
                "api": zeile["production_kwh_api"],
                "differenz": round(zeile["differenz"], 3),
            }
            for _, zeile in abweichend.head(20).iterrows()
        ],
    }
