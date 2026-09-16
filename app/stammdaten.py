import logging

from sqlalchemy import select

from app.config import load_plant_config
from app.database import SessionLocal
from app.models import PlantConfig

logger = logging.getLogger(__name__)


def seed_plant_config() -> int:
    """Gleicht die Tabelle plant_config mit plant.yaml ab und liefert die id."""
    settings = load_plant_config()

    with SessionLocal() as session:
        plant = session.execute(
            select(PlantConfig).where(PlantConfig.name == settings.name)
        ).scalar_one_or_none()

        if plant is None:
            plant = PlantConfig(name=settings.name)
            session.add(plant)

        plant.latitude = settings.location.latitude
        plant.longitude = settings.location.longitude
        plant.tilt_deg = settings.panel.tilt_deg
        plant.azimuth_deg = settings.panel.azimuth_deg
        plant.capacity_w = settings.panel.capacity_w
        plant.installation_date = settings.installation_date
        plant.acquisition_cost_eur = settings.economics.acquisition_cost_eur
        plant.subsidy_eur = settings.economics.subsidy_eur
        session.commit()
        return plant.id