from datetime import date

import httpx
import pandas as pd
import pandera.pandas as pa

from app.adapters.base import SourceAdapter
from app.config import PlantSettings, SourceSettings
from app.retry import mit_wiederholung
from app.schemas import validiere_nachsichtig


class OpenMeteoAdapter(SourceAdapter):
    """Gemeinsamer Ablauf aller Open-Meteo-Endpunkte.

    Unterklassen legen die Spaltenabbildung, das Validierungsschema und
    bei Bedarf zusätzliche Abfrageparameter fest. Der Ablauf selbst,
    also Abruf, Zeitzonenbehandlung und Validierung, steht nur hier.
    """

    column_map: dict[str, str] = {"time": "timestamp"}
    schema: pa.DataFrameSchema

    def __init__(self, plant: PlantSettings, source: SourceSettings, plant_id: int):
        self.plant = plant
        self.source = source
        self.plant_id = plant_id

    def extra_params(self) -> dict:
        """Parameter, die nur einzelne Endpunkte kennen."""
        return {}

    def fetch(self, start: date, end: date) -> pd.DataFrame:
        params = {
            "latitude": self.plant.location.latitude,
            "longitude": self.plant.location.longitude,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(self.source.variables),
            "timezone": "UTC",
            **self.extra_params(),
        }

        response = mit_wiederholung(
            lambda: httpx.get(self.source.url, params=params, timeout=30)
        )

        frame = pd.DataFrame(response.json()["hourly"])
        # Die API liefert Zeitstempel ohne Zeitzonenangabe. Da timezone=UTC
        # angefragt wurde, wird die Zeitzone hier explizit gesetzt.
        frame["time"] = pd.to_datetime(frame["time"]).dt.tz_localize("UTC")
        frame = frame.rename(columns=self.column_map)
        frame["plant_id"] = self.plant_id
        return validiere_nachsichtig(self.schema, frame, self.name)
