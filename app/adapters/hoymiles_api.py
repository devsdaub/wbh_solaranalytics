import logging
import struct
import time
from datetime import date

import httpx
import pandas as pd

from app.adapters.base import SourceAdapter
from app.adapters.hoymiles_auth import HoymilesAuth, api_ok
from app.config import HoymilesAuthSettings, PlantSettings, SourceSettings
from app.retry import mit_wiederholung
from app.schemas import ENERGY_REPORT_SCHEMA

logger = logging.getLogger(__name__)

ABSTAND_SEKUNDEN = 1.5


class HoymilesApiError(Exception):
    pass


def _varint(daten: bytes, pos: int) -> tuple[int, int]:
    ergebnis, verschiebung = 0, 0
    while pos < len(daten):
        byte = daten[pos]
        pos += 1
        ergebnis |= (byte & 0x7F) << verschiebung
        verschiebung += 7
        if not byte & 0x80:
            break
    return ergebnis, pos


def parse_protobuf_chart(daten: bytes) -> dict[str, list]:
    """Liest das Diagrammformat der Hoymiles-API.

    Feld 1 sind die Beschriftungen, Feld 2 eine Unternachricht mit Messwerten.
    """
    labels: list[str] = []
    reihen: dict[str, list[float]] = {}
    pos = 0

    while pos < len(daten):
        tag, pos = _varint(daten, pos)
        feld, typ = tag >> 3, tag & 0x07

        if typ != 2:
            if typ == 0:
                _, pos = _varint(daten, pos)
            elif typ in (1, 5):
                pos += 8 if typ == 1 else 4
            else:
                break
            continue

        laenge, pos = _varint(daten, pos)
        inhalt = daten[pos:pos + laenge]
        pos += laenge

        if feld == 1:
            labels.append(inhalt.decode("utf-8", errors="replace"))
        elif feld == 2:
            name, werte = "", []
            unter = 0
            while unter < len(inhalt):
                utag, unter = _varint(inhalt, unter)
                if utag & 0x07 != 2:
                    break
                ulaenge, unter = _varint(inhalt, unter)
                uinhalt = inhalt[unter:unter + ulaenge]
                unter += ulaenge

                if utag >> 3 == 1:
                    name = uinhalt.decode("utf-8", errors="replace")
                elif utag >> 3 == 2:
                    werte = [
                        struct.unpack("<f", uinhalt[i:i + 4])[0]
                        for i in range(0, len(uinhalt) - 3, 4)
                    ]
            if name and werte:
                reihen[name] = werte

    return {"labels": labels, **reihen}


class HoymilesApiAdapter(SourceAdapter):
    """Holt Tagesproduktion aus der Hoymiles S-Miles Cloud."""

    name = "hoymiles_api"

    def __init__(
        self,
        plant: PlantSettings,
        source: SourceSettings,
        plant_id: int,
        zugang: HoymilesAuthSettings,
    ):
        self.plant = plant
        self.source = source
        self.plant_id = plant_id
        self.station_id = zugang.station_id
        self.base_url = zugang.base_url.rstrip("/")
        self._auth = HoymilesAuth(zugang.username, zugang.password, zugang.base_url)

    def _post(self, client: httpx.Client, pfad: str, rumpf: dict) -> httpx.Response:
        """Sendet die Anfrage und meldet sich bei abgelaufenem Token neu an."""
        for _ in range(2):
            kopf = self._auth.header()
            antwort = mit_wiederholung(
                lambda k=kopf: client.post(
                    f"{self.base_url}{pfad}", json=rumpf, headers=k
                )
            )

            if "json" in antwort.headers.get("content-type", ""):
                daten = antwort.json()
                meldung = str(daten.get("message", "")).lower()
                if not api_ok(daten.get("status")) and "token" in meldung:
                    logger.info("Token abgelaufen, neue Anmeldung")
                    self._auth.verwerfen()
                    continue

            return antwort

        raise HoymilesApiError(f"{pfad}: Anmeldung nach Token-Erneuerung fehlgeschlagen")

    def fetch(self, start: date, end: date) -> pd.DataFrame:
        eintraege: list[dict] = []

        with httpx.Client(timeout=30) as client:
            monat = start.replace(day=1)
            while monat <= end:
                eintraege.extend(self._monat_holen(client, monat, start, end))

                monat = (
                    monat.replace(year=monat.year + 1, month=1)
                    if monat.month == 12
                    else monat.replace(month=monat.month + 1)
                )
                if monat <= end:
                    time.sleep(ABSTAND_SEKUNDEN)

        if not eintraege:
            return pd.DataFrame(columns=["plant_id", "date", "production_kwh"])

        frame = pd.DataFrame(eintraege).drop_duplicates(subset=["date"])
        frame = frame.sort_values("date").reset_index(drop=True)
        frame["plant_id"] = self.plant_id

        logger.info("Hoymiles-API: %s Tage von %s bis %s", len(frame), start, end)
        return ENERGY_REPORT_SCHEMA.validate(frame)

    def _monat_holen(
        self, client: httpx.Client, monat: date, von: date, bis: date
    ) -> list[dict]:
        antwort = self._post(
            client,
            "/pvm-data/api/0/station/data/count_eq_by_day_of_month",
            {"sid": self.station_id, "date": monat.strftime("%Y-%m")},
        )

        geparst = parse_protobuf_chart(antwort.content)
        labels = geparst.get("labels", [])
        werte = geparst.get("pv_eq", [])

        if not labels or not werte:
            logger.warning("Keine Daten für %s", monat.strftime("%Y-%m"))
            return []

        eintraege: list[dict] = []
        uebersprungen: list[date] = []
        for label, wattstunden in zip(labels, werte, strict=False):
            try:
                tag = date(monat.year, monat.month, int(label))
            except (ValueError, OverflowError):
                continue

            if not von <= tag <= bis:
                continue

            kwh = round(float(wattstunden) / 1000, 4)

            # Exakt 0 heisst hier "nichts empfangen", nicht "nichts erzeugt".
            # Belegt an den Tagen vor der Inbetriebnahme, die alle auf 0
            # stehen, waehrend der Installationstag selbst 0,007 kWh zeigt.
            # Der Tag wird ausgelassen, damit er als Luecke erkennbar bleibt.
            if kwh <= 0:
                uebersprungen.append(tag)
                continue

            eintraege.append({"date": pd.Timestamp(tag), "production_kwh": kwh})

        if uebersprungen:
            logger.info("%s: %s Tage ohne Messwert ausgelassen (%s bis %s)",
                        monat.strftime("%Y-%m"), len(uebersprungen),
                        min(uebersprungen), max(uebersprungen))

        return eintraege

    def realtime(self) -> dict | None:
        """Aktuelle Leistung und Tagesertrag, für den Verbindungstest."""
        with httpx.Client(timeout=30) as client:
            antwort = self._post(
                client,
                "/pvm-data/api/0/station/data/count_station_real_data",
                {"sid": self.station_id},
            )
            daten = antwort.json()

            if not api_ok(daten.get("status")):
                return None

            inner = daten.get("data") or {}
            return {
                "heute_kwh": round(float(inner.get("today_eq") or 0) / 1000, 3),
                "leistung_w": float(inner.get("real_power") or 0),
                "gesamt_kwh": round(float(inner.get("total_eq") or 0) / 1000, 1),
            }
