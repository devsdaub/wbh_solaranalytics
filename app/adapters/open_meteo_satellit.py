from app.adapters.open_meteo import OpenMeteoAdapter
from app.adapters.open_meteo_weather import flaechen_params
from app.schemas import HOURLY_SATELLIT_SCHEMA
from app.standorte import Standort


class OpenMeteoSatellitAdapter(OpenMeteoAdapter):
    """Einstrahlung auf die Modulfläche aus dem Satellitendatensatz SARAH-3."""

    name = "open_meteo_satellit"
    schema = HOURLY_SATELLIT_SCHEMA
    column_map = {"time": "timestamp", "global_tilted_irradiance": "gti_satellit"}

    def extra_params(self, standort: Standort) -> dict:
        return flaechen_params(standort)
