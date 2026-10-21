from app.adapters.open_meteo import OpenMeteoAdapter
from app.schemas import HOURLY_WEATHER_SCHEMA
from app.standorte import Standort


def to_open_meteo_azimuth(azimuth_deg: float) -> float:
    """Nord-basiert (180 = Süd) in Open-Meteo-Konvention (0 = Süd, -90 = Ost)."""
    return (azimuth_deg % 360) - 180


def flaechen_params(standort: Standort) -> dict:
    return {
        "tilt": standort.tilt_deg,
        "azimuth": to_open_meteo_azimuth(standort.azimuth_deg),
    }


class OpenMeteoWeatherAdapter(OpenMeteoAdapter):
    """Stündliches Wetter im Rückblick, aus den ICON-D2-Analysen."""

    name = "open_meteo_weather"
    schema = HOURLY_WEATHER_SCHEMA
    column_map = {
        "time": "timestamp",
        "global_tilted_irradiance": "gti",
        "temperature_2m": "temperature",
    }

    def extra_params(self, standort: Standort) -> dict:
        return flaechen_params(standort)
