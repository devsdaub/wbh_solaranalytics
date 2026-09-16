import logging
from pathlib import Path

import pandas as pd

from app.adapters.base import FileAdapter
from app.config import load_plant_config
from app.schemas import ENERGY_REPORT_SCHEMA

logger = logging.getLogger(__name__)

PRODUCTION_COLUMN = "Production (kWh)"

DATE_COLUMNS = ("Date", "Time")

CAPACITY_COLUMNS = {
    "Capacity (kW)": 1000,
    "Rated Power (W)": 1,
}


class HoymilesEnergyAdapter(FileAdapter):
    """Liest den manuell exportierten Energy-Report aus dem Hoymiles-Portal.
    """

    name = "hoymiles_energy"

    def parse(self, path: Path, plant_id: int) -> pd.DataFrame:
        frame = pd.read_csv(path)
        vorhanden = list(frame.columns)
        logger.info("Hoymiles-Export gelesen: %s Zeilen, Spalten %s",
                    len(frame), vorhanden)

        if PRODUCTION_COLUMN not in frame.columns:
            raise ValueError(
                f"Kein Energy-Report. Erwartete Spalte '{PRODUCTION_COLUMN}' "
                f"fehlt. Gefunden: {vorhanden}"
            )

        datumsspalte = next(
            (spalte for spalte in DATE_COLUMNS if spalte in frame.columns), None
        )
        if datumsspalte is None:
            raise ValueError(
                f"Keine Datumsspalte gefunden. Erwartet eine von {DATE_COLUMNS}, "
                f"vorhanden: {vorhanden}"
            )

        self._pruefe_nennleistung(frame)

        # Nur die benötigten Spalten übernehmen.
        behalten = [datumsspalte, PRODUCTION_COLUMN]
        verworfen = [s for s in vorhanden if s not in behalten]
        if verworfen:
            logger.info("Nicht übernommene Spalten: %s", verworfen)

        frame = frame[behalten].rename(columns={
            datumsspalte: "date",
            PRODUCTION_COLUMN: "production_kwh",
        })
        frame["date"] = pd.to_datetime(frame["date"])
        frame["plant_id"] = plant_id

        return ENERGY_REPORT_SCHEMA.validate(frame)

    def _pruefe_nennleistung(self, frame: pd.DataFrame) -> None:
        """Vergleicht die Anlagenleistung im Export mit der Konfiguration.
        """
        spalte = next(
            (s for s in CAPACITY_COLUMNS if s in frame.columns), None
        )
        if spalte is None:
            return

        faktor = CAPACITY_COLUMNS[spalte]
        konfiguriert = load_plant_config().panel.module_capacity_wp

        for wert in frame[spalte].dropna().unique():
            watt = round(float(wert) * faktor)
            if watt != konfiguriert:
                logger.warning(
                    "Modulleistung im Export (%s W aus Spalte '%s') weicht "
                    "von der Konfiguration ab (%s W)",
                    watt, spalte, konfiguriert,
                )