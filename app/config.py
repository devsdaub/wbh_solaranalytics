import os
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/app/config"))


class Location(BaseModel):
    latitude: float
    longitude: float
    city: str


class Panel(BaseModel):
    capacity_w: int
    module_capacity_wp: int
    tilt_deg: int
    azimuth_deg: int


class Economics(BaseModel):
    acquisition_cost_eur: float
    subsidy_eur: float
    electricity_price_eur_kwh: float


class PlantSettings(BaseModel):
    name: str
    installation_date: date
    location: Location
    panel: Panel
    economics: Economics


def load_plant_config() -> PlantSettings:
    path = CONFIG_DIR / "plant.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PlantSettings.model_validate(raw["plant"])


class SourceSettings(BaseModel):
    enabled: bool
    url: str
    default_days_back: int
    variables: list[str]


class SourcesSettings(BaseModel):
    open_meteo_weather: SourceSettings
    open_meteo_air: SourceSettings
    hoymiles_api: SourceSettings


def load_sources_config() -> SourcesSettings:
    path = CONFIG_DIR / "sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return SourcesSettings.model_validate(raw["sources"])


def save_sources_config(settings: SourcesSettings) -> None:
    path = CONFIG_DIR / "sources.yaml"
    inhalt = {"sources": settings.model_dump()}
    path.write_text(
        yaml.safe_dump(inhalt, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


class JobSettings(BaseModel):
    interval_minutes: int = Field(ge=1)
    enabled: bool


class SchedulerSettings(BaseModel):
    enabled: bool
    jobs: dict[str, JobSettings]


def load_scheduler_config() -> SchedulerSettings:
    path = CONFIG_DIR / "scheduler.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return SchedulerSettings.model_validate(raw["scheduler"])


def save_scheduler_config(settings: SchedulerSettings) -> None:
    path = CONFIG_DIR / "scheduler.yaml"
    inhalt = {"scheduler": settings.model_dump()}
    path.write_text(
        yaml.safe_dump(inhalt, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


class HoymilesAuthSettings(BaseModel):
    username: str
    password: str
    station_id: str
    base_url: str = "https://neapi.hoymiles.com"


def load_hoymiles_auth() -> HoymilesAuthSettings | None:
    """Liest die Zugangsdaten, oder None wenn die Datei fehlt."""
    path = CONFIG_DIR / "hoymiles_auth.yaml"
    if not path.exists():
        return None

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return HoymilesAuthSettings.model_validate(raw["hoymiles_auth"])
