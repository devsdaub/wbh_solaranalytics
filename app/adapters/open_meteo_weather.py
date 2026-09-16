from app.adapters.open_meteo import OpenMeteoAdapter
from app.schemas import HOURLY_WEATHER_SCHEMA


def to_open_meteo_azimuth(azimuth_deg: float) -> float:
    """Rechnet einen Nord-basierten Azimut in die Konvention von Open-Meteo um.

    Anlagendaten sind Nord-basiert (0 = Nord, 180 = Süd, 270 = West).
    Open-Meteo erwartet Süd-basierte Werte zwischen -180 und 180
    (0 = Süd, -90 = Ost, +90 = West).
    """
    return (azimuth_deg % 360) - 180


class OpenMeteoWeatherAdapter(OpenMeteoAdapter):
    """Liest stündliche Wetterdaten aus dem Open-Meteo-Archiv."""

    name = "open_meteo_weather"
    schema = HOURLY_WEATHER_SCHEMA
    column_map = {
        "time": "timestamp",
        "global_tilted_irradiance": "gti",
        "temperature_2m": "temperature",
    }

    def extra_params(self) -> dict:
        return {
            "tilt": self.plant.panel.tilt_deg,
            "azimuth": to_open_meteo_azimuth(self.plant.panel.azimuth_deg),
        }