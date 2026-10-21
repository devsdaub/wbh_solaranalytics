import pandas as pd

from app.adapters.open_meteo import OpenMeteoAdapter
from app.adapters.open_meteo_weather import flaechen_params
from app.schemas import HOURLY_FORECAST_SCHEMA, VORHERSAGE_SCHEMA
from app.standorte import Standort

SPALTEN = {
    "global_tilted_irradiance": "gti",
    "temperature_2m": "temperature",
    "cloud_cover": "cloud_cover",
    "sunshine_duration": "sunshine_duration",
}


class OpenMeteoVorhersageAdapter(OpenMeteoAdapter):
    """Aktuelle ICON-Vorhersage für die kommenden Tage."""

    name = "open_meteo_vorhersage"
    schema = VORHERSAGE_SCHEMA
    column_map = {
        "time": "timestamp",
        "global_tilted_irradiance": "gti",
        "temperature_2m": "temperature",
    }

    def extra_params(self, standort: Standort) -> dict:
        return flaechen_params(standort)


class OpenMeteoVorhersagearchivAdapter(OpenMeteoAdapter):
    """Archivierte ICON-Vorhersagen: was vor 1 bis 6 Tagen für jede Stunde vorhergesagt war."""

    name = "open_meteo_vorhersagearchiv"
    schema = HOURLY_FORECAST_SCHEMA

    def vorlaeufe(self) -> range:
        return range(1, (self.source.max_vorlauf or 6) + 1)

    def abgefragte_variablen(self) -> list[str]:
        return [f"{variable}_previous_day{tage}"
                for tage in self.vorlaeufe() for variable in self.source.variables]

    def extra_params(self, standort: Standort) -> dict:
        return flaechen_params(standort)

    def aufbereiten(self, frame: pd.DataFrame) -> pd.DataFrame:
        # aus einer breiten Tabelle je Vorlauf eine lange mit der Spalte vorlauf
        teile = []
        for tage in self.vorlaeufe():
            teil = pd.DataFrame({"timestamp": frame["time"], "vorlauf": tage})
            for variable in self.source.variables:
                spalte = f"{variable}_previous_day{tage}"
                teil[SPALTEN.get(variable, variable)] = (
                    frame[spalte] if spalte in frame else None
                )
            teile.append(teil)
        return pd.concat(teile, ignore_index=True)
