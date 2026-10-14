from datetime import date

import httpx
import pandas as pd
import pandera.pandas as pa

from app.adapters.base import SourceAdapter
from app.config import PlantSettings, SourceSettings
from app.retry import mit_wiederholung
from app.schemas import validiere_nachsichtig
from app.standorte import Standort, standorte_im_zeitraum


class OpenMeteoAdapter(SourceAdapter):
    """Gemeinsamer Ablauf aller Open-Meteo-Endpunkte."""

    column_map: dict[str, str] = {"time": "timestamp"}
    schema: pa.DataFrameSchema
    zeitlimit_sekunden = 120

    def __init__(self, plant: PlantSettings, source: SourceSettings, plant_id: int):
        self.plant = plant
        self.source = source
        self.plant_id = plant_id

    def extra_params(self, standort: Standort) -> dict:
        return {}

    def abgefragte_variablen(self) -> list[str]:
        return self.source.variables

    def aufbereiten(self, frame: pd.DataFrame) -> pd.DataFrame:
        return frame.rename(columns=self.column_map)

    def _abruf(self, standort: Standort, start: date, end: date) -> pd.DataFrame:
        params = {
            "latitude": standort.latitude,
            "longitude": standort.longitude,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(self.abgefragte_variablen()),
            "timezone": "UTC",
            **self.extra_params(standort),
        }
        if self.source.models:
            params["models"] = self.source.models

        response = mit_wiederholung(
            lambda: httpx.get(self.source.url, params=params,
                              timeout=self.zeitlimit_sekunden)
        )

        frame = pd.DataFrame(response.json()["hourly"])
        # timezone=UTC liefert Zeitstempel ohne Angabe, deshalb hier gesetzt
        frame["time"] = pd.to_datetime(frame["time"]).dt.tz_localize("UTC")
        return self.aufbereiten(frame)

    def fetch(self, start: date, end: date) -> pd.DataFrame:
        # je Standort ein Abruf mit dessen Koordinaten, Neigung und Ausrichtung
        teile = [
            self._abruf(standort, von, bis)
            for standort, von, bis in standorte_im_zeitraum(self.plant, start, end)
        ]
        frame = pd.concat(teile, ignore_index=True)
        frame["plant_id"] = self.plant_id
        return validiere_nachsichtig(self.schema, frame, self.name)
