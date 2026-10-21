import logging

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)

# create_all legt neue Tabellen an, ergänzt aber keine Spalten an bestehenden
NEUE_SPALTEN = [
    ("hourly_weather", "gti_satellit", "DOUBLE PRECISION"),
    ("daily_facts", "gti_satellit_kwh", "DOUBLE PRECISION"),
]


def ergaenze_spalten() -> None:
    with engine.begin() as verbindung:
        for tabelle, spalte, typ in NEUE_SPALTEN:
            verbindung.execute(text(
                f"ALTER TABLE {tabelle} ADD COLUMN IF NOT EXISTS {spalte} {typ}"
            ))
    logger.info("Schema geprüft, %s Spalten sichergestellt", len(NEUE_SPALTEN))
