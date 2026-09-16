from app.adapters.open_meteo import OpenMeteoAdapter
from app.schemas import HOURLY_AIR_SCHEMA


class OpenMeteoAirAdapter(OpenMeteoAdapter):
    """Liest stündliche Luftqualitätsdaten von Open-Meteo."""

    name = "open_meteo_air"
    schema = HOURLY_AIR_SCHEMA