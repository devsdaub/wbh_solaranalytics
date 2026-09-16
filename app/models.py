from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PlantConfig(Base):
    __tablename__ = "plant_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    latitude: Mapped[float]
    longitude: Mapped[float]
    tilt_deg: Mapped[int]
    azimuth_deg: Mapped[int]
    capacity_w: Mapped[int]
    installation_date: Mapped[date]
    acquisition_cost_eur: Mapped[float]
    subsidy_eur: Mapped[float]


class DailyFact(Base):
    __tablename__ = "daily_facts"
    __table_args__ = (UniqueConstraint("plant_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plant_config.id"))
    date: Mapped[date]
    production_kwh: Mapped[float | None]
    gti_kwh: Mapped[float | None]
    avg_temperature: Mapped[float | None]
    avg_cloud_cover: Mapped[int | None]
    max_dust: Mapped[float | None]
    avg_pm10: Mapped[float | None]
    eq: Mapped[float | None]
    hours: Mapped[int | None]


class HourlyWeather(Base):
    __tablename__ = "hourly_weather"
    __table_args__ = (UniqueConstraint("plant_id", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plant_config.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    gti: Mapped[float | None]
    temperature: Mapped[float | None]
    cloud_cover: Mapped[int | None]
    cloud_cover_low: Mapped[int | None]
    cloud_cover_mid: Mapped[int | None]
    cloud_cover_high: Mapped[int | None]
    visibility: Mapped[float | None]
    dust: Mapped[float | None]
    pm10: Mapped[float | None]


class PowerReading(Base):
    __tablename__ = "power_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plant_config.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    power_w: Mapped[int]


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str]
    status: Mapped[str]
    records: Mapped[int | None]
    days: Mapped[int | None]
    error: Mapped[str | None]