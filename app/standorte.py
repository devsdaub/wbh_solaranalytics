from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from app.config import PlantSettings


@dataclass(frozen=True)
class Standort:
    nummer: int
    city: str
    latitude: float
    longitude: float
    tilt_deg: int
    azimuth_deg: int


def alle_standorte(plant: PlantSettings) -> list[tuple[Standort, date | None]]:
    """Alle Standorte mit ihrem letzten gültigen Tag, der aktuelle gilt offen."""
    frueher = sorted(plant.frueher, key=lambda s: s.bis)
    liste = [
        (Standort(nummer, s.city, s.latitude, s.longitude,
                  s.tilt_deg or plant.panel.tilt_deg, s.azimuth_deg), s.bis)
        for nummer, s in enumerate(frueher)
    ]
    aktuell = Standort(
        len(frueher), plant.location.city, plant.location.latitude,
        plant.location.longitude, plant.panel.tilt_deg, plant.panel.azimuth_deg,
    )
    return liste + [(aktuell, None)]


def standort_am(plant: PlantSettings, tag: date) -> Standort:
    for standort, bis in alle_standorte(plant):
        if bis is None or tag <= bis:
            return standort


def standorte_im_zeitraum(
    plant: PlantSettings, start: date, end: date
) -> list[tuple[Standort, date, date]]:
    """Teilt einen Zeitraum an den Umzugsgrenzen in Abschnitte je Standort."""
    abschnitte = []
    von = start
    for standort, bis in alle_standorte(plant):
        if von > end:
            break
        if bis is not None and bis < von:
            continue
        ende = end if bis is None else min(bis, end)
        abschnitte.append((standort, von, ende))
        von = ende + timedelta(days=1)
    return abschnitte


def standortnummern(plant: PlantSettings, tage: pd.Series) -> pd.Series:
    return pd.Series(
        [standort_am(plant, pd.Timestamp(t).date()).nummer for t in tage],
        index=tage.index, dtype=float,
    )


def ist_uebergang(plant: PlantSettings, tag: date) -> bool:
    zeitraum = plant.uebergang
    return zeitraum is not None and zeitraum.von <= tag <= zeitraum.bis
