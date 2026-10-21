import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.adapters.open_meteo_vorhersage import OpenMeteoVorhersageAdapter
from app.analytics.artefakte import lade_ergebnisse, lade_modell
from app.analytics.auswahl import STANDARD, eingesetztes_verfahren
from app.analytics.bewertung import JAHRESZEITEN, kennzahlen
from app.analytics.merkmale import (
    AUSFALL_SCHWELLE_KWH,
    ZIELGROESSE,
    ergaenze_anlage,
    lade_stundenvorhersage,
    verdichte_auf_tage,
)
from app.analytics.modelle import BEZEICHNUNGEN, ertragsquote, faustregel_nachgefuehrt, gleitende_quote
from app.analytics.sonnenstand import tageslaenge_stunden
from app.config import load_plant_config, load_sources_config
from app.database import SessionLocal
from app.models import DailyFact, PrognoseArchiv
from app.standorte import ist_uebergang, standort_am, standortnummern

logger = logging.getLogger(__name__)

LOKAL = ZoneInfo("Europe/Berlin")
# das Archiv im Rückblick lässt sich nur für die Faustregel über alle Vorläufe nachrechnen
VERFAHREN = STANDARD

# ab dieser Ortszeit wird die Prognose des Tages festgeschrieben
ARCHIV_AB_STUNDE = 20

FENSTER_SPANNE_TAGE = 60
MIN_TAGE_SPANNE = 15
QUANTILE_SPANNE = (0.1, 0.9)
ERSATZ_SPANNE = (0.6, 1.5)

CACHE_SEKUNDEN = 1800
WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

_cache: dict = {"zeit": 0.0, "stichtag": None, "daten": None}
_archiv_sperre = threading.Lock()


def heute() -> date:
    return datetime.now(LOKAL).date()


def _r(wert, stellen: int = 2):
    if wert is None or (isinstance(wert, float) and np.isnan(wert)):
        return None
    return round(float(wert), stellen)


def max_vorlauf() -> int:
    return load_sources_config().open_meteo_vorhersagearchiv.max_vorlauf or 6


def _messungen(session, plant_id: int) -> pd.DataFrame:
    """Messtage für Quote und Spanne, ohne Ausfalltage und ohne Übergangszeit."""
    plant = load_plant_config()
    zeilen = session.execute(
        select(DailyFact.date, DailyFact.production_kwh)
        .where(DailyFact.plant_id == plant_id, DailyFact.production_kwh.isnot(None))
    ).all()
    frame = pd.DataFrame(zeilen, columns=["date", ZIELGROESSE])
    if frame.empty:
        return frame
    unbrauchbar = (frame[ZIELGROESSE] <= AUSFALL_SCHWELLE_KWH) | frame["date"].map(
        lambda tag: ist_uebergang(plant, tag)).astype(bool)
    return frame[~unbrauchbar].sort_values("date").reset_index(drop=True)


def _vorhersage_tage(session, plant_id: int, vorlauf: int) -> pd.DataFrame:
    stunden = lade_stundenvorhersage(session, plant_id, vorlauf)
    if stunden.empty:
        return pd.DataFrame(columns=["date", "gti_kwh_m2", "sonnenstunden"])
    return verdichte_auf_tage(stunden)[["date", "gti_kwh_m2", "sonnenstunden"]]


def lade_archiv(session, plant_id: int, verfahren: str = VERFAHREN) -> pd.DataFrame:
    """Alle festgeschriebenen Prognosen eines Verfahrens, mit Messung und Standort."""
    zeilen = session.execute(
        select(PrognoseArchiv.stichtag, PrognoseArchiv.zieltag, PrognoseArchiv.vorlauf,
               PrognoseArchiv.herkunft, PrognoseArchiv.gti_kwh, PrognoseArchiv.sonnenstunden,
               PrognoseArchiv.quote, PrognoseArchiv.prognose_kwh, PrognoseArchiv.unten_kwh,
               PrognoseArchiv.oben_kwh)
        .where(PrognoseArchiv.plant_id == plant_id, PrognoseArchiv.verfahren == verfahren)
        .order_by(PrognoseArchiv.zieltag)
    ).all()
    archiv = pd.DataFrame(zeilen, columns=[
        "stichtag", "zieltag", "vorlauf", "herkunft", "gti_kwh", "sonnenstunden",
        "quote", "prognose_kwh", "unten_kwh", "oben_kwh",
    ])
    messungen = _messungen(session, plant_id).rename(columns={"date": "zieltag", ZIELGROESSE: "ist"})
    archiv = archiv.merge(messungen, on="zieltag", how="left")
    archiv["standort"] = standortnummern(load_plant_config(), archiv["zieltag"]).to_numpy()
    return archiv


def berechne_spanne(verlauf: pd.DataFrame, bis: date, standort: float,
                    prognose: float) -> tuple[float, float]:
    """10. und 90. Perzentil der Abweichungen in kWh der letzten 60 bewerteten Tage mit gleichem Vorlauf."""
    frueher = verlauf[
        (verlauf["zieltag"] <= bis) & (verlauf["standort"] == standort)
        & verlauf["ist"].notna() & verlauf["prognose_kwh"].notna()
    ].sort_values("zieltag").tail(FENSTER_SPANNE_TAGE)
    if len(frueher) < MIN_TAGE_SPANNE:
        return prognose * ERSATZ_SPANNE[0], prognose * ERSATZ_SPANNE[1]
    unten, oben = np.quantile(frueher["ist"] - frueher["prognose_kwh"], QUANTILE_SPANNE)
    return max(prognose + min(unten, 0.0), 0.0), prognose + max(oben, 0.0)


def _schreibe(plant_id: int, zeilen: list[dict], verfahren: str = VERFAHREN) -> int:
    if not zeilen:
        return 0
    erstellt = datetime.now(timezone.utc)
    werte = [{"plant_id": plant_id, "verfahren": verfahren, "erstellt_am": erstellt, **z} for z in zeilen]
    with SessionLocal() as session:
        for beginn in range(0, len(werte), 2000):
            statement = insert(PrognoseArchiv).values(werte[beginn:beginn + 2000])
            # festgeschriebene Prognosen werden nie überschrieben
            session.execute(statement.on_conflict_do_nothing(
                index_elements=["plant_id", "zieltag", "vorlauf", "verfahren"]
            ))
        session.commit()
    return len(werte)


def archiviere_rueckblick(plant_id: int) -> int:
    """Trägt für vergangene Tage nach, was an jedem Stichtag prognostiziert worden wäre."""
    plant = load_plant_config()
    gestern = heute() - timedelta(days=1)
    with SessionLocal() as session:
        messungen = _messungen(session, plant_id)
        vortag = _vorhersage_tage(session, plant_id, 1)[["date", "gti_kwh_m2"]].rename(
            columns={"gti_kwh_m2": "gti_quote"})
        archiv = lade_archiv(session, plant_id)
        ziele = {h: _vorhersage_tage(session, plant_id, h) for h in range(1, max_vorlauf() + 1)}

    neue = []
    for vorlauf, ziel in ziele.items():
        frame = (ziel.merge(vortag, on="date", how="outer")
                 .merge(messungen, on="date", how="left")
                 .sort_values("date").reset_index(drop=True))
        frame = frame[frame["date"] <= gestern].reset_index(drop=True)
        if frame.empty:
            continue
        frame["standort"] = standortnummern(plant, frame["date"]).to_numpy()
        frame["eins"] = 1.0
        # Messwerte liegen bis zum Vortag des Stichtags vor, Stichtag ist Zieltag minus Vorlauf
        frame["quote"] = faustregel_nachgefuehrt(
            frame, "gti_quote", abstand=vorlauf + 1, gti_ziel_spalte="eins")

        verlauf = archiv.loc[archiv["vorlauf"] == vorlauf,
                             ["zieltag", "standort", "prognose_kwh", "ist"]].reset_index(drop=True)
        bekannt = set(verlauf["zieltag"])
        for zeile in frame.itertuples():
            if zeile.date in bekannt or np.isnan(zeile.quote) or np.isnan(zeile.gti_kwh_m2):
                continue
            prognose = zeile.quote * zeile.gti_kwh_m2
            unten, oben = berechne_spanne(
                verlauf, zeile.date - timedelta(days=vorlauf + 1), zeile.standort, prognose)
            verlauf.loc[len(verlauf)] = [zeile.date, zeile.standort, prognose,
                                         getattr(zeile, ZIELGROESSE)]
            neue.append({
                "stichtag": zeile.date - timedelta(days=vorlauf), "zieltag": zeile.date,
                "vorlauf": vorlauf, "herkunft": "rueckblick",
                "gti_kwh": _r(zeile.gti_kwh_m2, 3), "sonnenstunden": _r(zeile.sonnenstunden, 2),
                "quote": _r(zeile.quote, 4), "prognose_kwh": _r(prognose, 3),
                "unten_kwh": _r(unten, 3), "oben_kwh": _r(oben, 3),
            })
    anzahl = _schreibe(plant_id, neue)
    if anzahl:
        logger.info("Prognosearchiv: %s Prognosen im Rückblick nachgetragen", anzahl)
    return anzahl


def _symbol(sonnenstunden, tageslaenge, regen_mm=0.0) -> str:
    if sonnenstunden is None or np.isnan(sonnenstunden):
        return "bedeckt"
    anteil = sonnenstunden / max(tageslaenge, 1.0)
    if (regen_mm or 0.0) >= 3 and anteil < 0.35:
        return "regen"
    if anteil > 0.72:
        return "sonne"
    if anteil > 0.48:
        return "heiter"
    return "wolkig" if anteil > 0.22 else "bedeckt"


def _tageslaenge(tage: pd.Series) -> np.ndarray:
    doy = pd.to_datetime(tage).dt.dayofyear.to_numpy(dtype=float)
    return tageslaenge_stunden(doy, load_plant_config().location.latitude)


def _lernverfahren(taeglich: pd.DataFrame) -> tuple[str | None, np.ndarray | None]:
    artefakt = lade_modell()
    if artefakt is None:
        return None, None
    X = taeglich[artefakt["merkmale"]].astype(float)
    werte = np.clip(artefakt["modell"].predict(X), 0, None) * artefakt.get("faktor", 1.0)
    return artefakt["name"], werte


def prognostiziere(plant_id: int = 1, neu_abrufen: bool = False) -> dict:
    """Ertrag für heute und die nächsten sechs Tage aus der aktuellen ICON-Vorhersage."""
    stichtag = heute()
    if (not neu_abrufen and _cache["daten"] is not None and _cache["stichtag"] == stichtag
            and time.time() - _cache["zeit"] < CACHE_SEKUNDEN):
        return _cache["daten"]

    plant = load_plant_config()
    quelle = load_sources_config().open_meteo_vorhersage
    letzter = stichtag + timedelta(days=quelle.max_vorlauf or 6)
    stunden = OpenMeteoVorhersageAdapter(plant, quelle, plant_id).fetch(stichtag, letzter)

    taeglich = verdichte_auf_tage(stunden)
    taeglich = taeglich[(taeglich["date"] >= stichtag) & (taeglich["date"] <= letzter)]
    if taeglich.empty:
        raise ValueError("Die Vorhersage lieferte keinen vollständigen Tag")
    taeglich = ergaenze_anlage(taeglich)
    lokal = pd.to_datetime(stunden["timestamp"], utc=True).dt.tz_convert(LOKAL).dt.date
    regen = stunden.assign(date=lokal).groupby("date")["precipitation"].sum()

    lern_name, lern_werte = _lernverfahren(taeglich)
    verfahren = eingesetztes_verfahren()
    if verfahren != STANDARD and (lern_name != verfahren or lern_werte is None):
        logger.warning("Modell für %s fehlt, die Prognose rechnet mit %s", verfahren, STANDARD)
        verfahren = STANDARD

    with SessionLocal() as session:
        messungen = _messungen(session, plant_id)
        vortag = _vorhersage_tage(session, plant_id, 1)
        archiv = lade_archiv(session, plant_id)
        eigenes = lade_archiv(session, plant_id, verfahren) if verfahren != STANDARD else archiv

    historie = messungen.merge(vortag, on="date", how="inner")
    historie["standort"] = standortnummern(plant, historie["date"]).to_numpy()
    aktuell = standort_am(plant, stichtag).nummer
    quote = gleitende_quote(
        pd.to_datetime(historie["date"]).to_numpy(dtype="datetime64[D]"),
        ertragsquote(historie), historie["standort"].to_numpy(dtype=float),
        np.datetime64(stichtag - timedelta(days=1)), float(aktuell),
    )
    tageslaenge = _tageslaenge(taeglich["date"])

    tage = []
    for i, zeile in enumerate(taeglich.itertuples()):
        vorlauf = (zeile.date - stichtag).days
        prognose = quote * zeile.gti_kwh_m2 if verfahren == STANDARD else float(lern_werte[i])
        stufe = min(max(vorlauf, 1), max_vorlauf())
        # bis das neue Verfahren genug eigene bewertete Tage hat, kommt die Spanne aus dem Archiv der Faustregel
        verlauf_stufe = eigenes[(eigenes["vorlauf"] == stufe) & eigenes["ist"].notna()]
        if len(verlauf_stufe) < MIN_TAGE_SPANNE:
            verlauf_stufe = archiv[archiv["vorlauf"] == stufe]
        unten, oben = berechne_spanne(verlauf_stufe, stichtag - timedelta(days=1), aktuell, prognose)
        regen_mm = float(regen.get(zeile.date, 0.0))
        tage.append({
            "datum": str(zeile.date),
            "name": "Heute" if vorlauf == 0 else "Morgen" if vorlauf == 1 else WOCHENTAGE[zeile.date.weekday()],
            "vorlauf": vorlauf,
            "gti": _r(zeile.gti_kwh_m2),
            "sonne_h": _r(zeile.sonnenstunden, 1),
            "wolken": _r(zeile.wolken_mittel, 0),
            "temp_max": _r(zeile.temp_max, 1),
            "regen_mm": _r(regen_mm, 1),
            "symbol": _symbol(zeile.sonnenstunden, tageslaenge[i], regen_mm),
            "prognose": _r(prognose),
            "unten": _r(unten),
            "oben": _r(oben),
            "lernverfahren": _r(lern_werte[i]) if lern_werte is not None else None,
        })

    daten = {
        "stichtag": str(stichtag),
        "abgerufen": datetime.now(timezone.utc).isoformat(),
        "verfahren": verfahren,
        "verfahren_name": BEZEICHNUNGEN[verfahren],
        "lernverfahren": lern_name,
        "lernverfahren_name": BEZEICHNUNGEN.get(lern_name) if lern_name else None,
        "quote": _r(quote, 3),
        "standort": standort_am(plant, stichtag).city,
        "tage": tage,
    }
    _cache.update(zeit=time.time(), stichtag=stichtag, daten=daten)
    return daten


def archiviere_heute(plant_id: int, jetzt: datetime | None = None) -> int:
    """Schreibt einmal am Abend die Prognose für die nächsten Tage fest."""
    jetzt = jetzt or datetime.now(LOKAL)
    if jetzt.hour < ARCHIV_AB_STUNDE:
        return 0
    with SessionLocal() as session:
        schon = session.execute(
            select(func.count()).select_from(PrognoseArchiv).where(
                PrognoseArchiv.plant_id == plant_id, PrognoseArchiv.stichtag == jetzt.date(),
                PrognoseArchiv.herkunft == "live")
        ).scalar_one()
    if schon:
        return 0

    vorschau = prognostiziere(plant_id, neu_abrufen=True)
    zeilen = [
        {
            "stichtag": date.fromisoformat(vorschau["stichtag"]),
            "zieltag": date.fromisoformat(tag["datum"]),
            "vorlauf": tag["vorlauf"], "herkunft": "live",
            "gti_kwh": tag["gti"], "sonnenstunden": tag["sonne_h"], "quote": vorschau["quote"],
            "prognose_kwh": tag["prognose"], "unten_kwh": tag["unten"], "oben_kwh": tag["oben"],
        }
        for tag in vorschau["tage"] if 1 <= tag["vorlauf"] <= max_vorlauf()
    ]
    anzahl = _schreibe(plant_id, zeilen, vorschau["verfahren"])
    logger.info("Prognosearchiv: %s Prognosen vom %s festgeschrieben (%s)", anzahl, vorschau["stichtag"], vorschau["verfahren"])
    return anzahl


def pflege_prognosearchiv(plant_id: int) -> dict:
    if not _archiv_sperre.acquire(blocking=False):
        return {"status": "uebersprungen", "grund": "läuft bereits"}
    try:
        return {"status": "ok", "rueckblick": archiviere_rueckblick(plant_id),
                "live": archiviere_heute(plant_id)}
    finally:
        _archiv_sperre.release()


def _auswertung_ab() -> date | None:
    ergebnisse = lade_ergebnisse()
    try:
        return date.fromisoformat(ergebnisse["lagen"]["vorhersage"]["schemata"]["S2"]["von"])
    except (TypeError, KeyError, ValueError):
        return None


def verlauf(plant_id: int = 1, tage: int = 180) -> dict:
    """Je Tag die Messung und die Prognosen mit Vorlauf 1 bis 6, dazu die Spanne vom Vortag."""
    bis = heute() - timedelta(days=1)
    von = bis - timedelta(days=tage - 1)
    with SessionLocal() as session:
        archiv = lade_archiv(session, plant_id)
        messungen = _messungen(session, plant_id).set_index("date")[ZIELGROESSE]

    archiv = archiv[(archiv["zieltag"] >= von) & (archiv["zieltag"] <= bis)].set_index(["zieltag", "vorlauf"])

    zeilen = []
    for tag in pd.date_range(von, bis, freq="D").date:
        zeile = {"datum": str(tag), "ist": _r(messungen.get(tag))}
        for vorlauf in range(1, max_vorlauf() + 1):
            vorhanden = (tag, vorlauf) in archiv.index
            for kurz, spalte in (("p", "prognose_kwh"), ("u", "unten_kwh"), ("o", "oben_kwh")):
                zeile[f"{kurz}{vorlauf}"] = _r(archiv.at[(tag, vorlauf), spalte]) if vorhanden else None
        zeile["herkunft"] = archiv.at[(tag, 1), "herkunft"] if (tag, 1) in archiv.index else None
        zeilen.append(zeile)
    return {"verfahren": VERFAHREN, "tage": zeilen}


def _treffer(gruppe: pd.DataFrame) -> dict:
    bewertet = gruppe[gruppe["ist"].notna() & gruppe["unten_kwh"].notna()]
    drin = (bewertet["ist"] >= bewertet["unten_kwh"]) & (bewertet["ist"] <= bewertet["oben_kwh"])
    return {
        "treffer_prozent": _r(100.0 * drin.mean(), 1) if len(bewertet) else None,
        "breite_kwh": _r((bewertet["oben_kwh"] - bewertet["unten_kwh"]).mean()) if len(bewertet) else None,
        "in_spanne": int(drin.sum()),
    }


def guete(plant_id: int = 1, ab: date | None = None) -> dict:
    """Fehler nach Vorlauf und Jahreszeit, Trefferquote der Spanne und das Protokoll der letzten Tage."""
    with SessionLocal() as session:
        archiv = lade_archiv(session, plant_id)
    ab = ab or _auswertung_ab()
    bewertet = archiv[archiv["ist"].notna()]
    if ab is not None:
        bewertet = bewertet[bewertet["zieltag"] >= ab]

    horizont = []
    for vorlauf, gruppe in bewertet.groupby("vorlauf"):
        werte = kennzahlen(gruppe["ist"].to_numpy(float), gruppe["prognose_kwh"].to_numpy(float))
        horizont.append({"vorlauf": int(vorlauf), **werte, **_treffer(gruppe)})

    eins = bewertet[bewertet["vorlauf"] == 1]
    zeit = pd.to_datetime(eins["zieltag"]).dt.month.map(JAHRESZEITEN)
    jahreszeiten = []
    for name in ("Winter", "Frühling", "Sommer", "Herbst"):
        gruppe = eins[(zeit == name).to_numpy()]
        werte = kennzahlen(gruppe["ist"].to_numpy(float), gruppe["prognose_kwh"].to_numpy(float))
        jahreszeiten.append({"name": name, **werte,
                             "mittlerer_ertrag": _r(gruppe["ist"].mean()) if len(gruppe) else None})

    grenze = heute() - timedelta(days=30)
    letzte = archiv[(archiv["vorlauf"] == 1) & (archiv["zieltag"] >= grenze) & archiv["ist"].notna()]
    letzte30 = {**kennzahlen(letzte["ist"].to_numpy(float), letzte["prognose_kwh"].to_numpy(float)),
                **_treffer(letzte)}

    protokoll_quelle = archiv[(archiv["vorlauf"] == 1) & (archiv["zieltag"] < heute())].tail(14)
    laengen = _tageslaenge(protokoll_quelle["zieltag"]) if len(protokoll_quelle) else []
    protokoll = [
        {
            "datum": str(z.zieltag), "herkunft": z.herkunft, "gti": _r(z.gti_kwh),
            "sonne_h": _r(z.sonnenstunden, 1), "symbol": _symbol(z.sonnenstunden, laengen[i]),
            "prognose": _r(z.prognose_kwh), "unten": _r(z.unten_kwh), "oben": _r(z.oben_kwh),
            "ist": _r(z.ist),
        }
        for i, z in enumerate(protokoll_quelle.itertuples())
    ][::-1]

    ergebnisse = lade_ergebnisse() or {}
    try:
        klima = ergebnisse["lagen"]["vorhersage"]["verfahren"]["klimatologie"]["S2"]["mae"]
    except KeyError:
        klima = None

    return {
        "verfahren": VERFAHREN,
        "auswertung_ab": str(ab) if ab else None,
        "horizont": horizont,
        "klimatologie_mae": klima,
        "jahreszeiten": jahreszeiten,
        "letzte_30_tage": letzte30,
        "gesamt": _treffer(eins),
        "protokoll": protokoll,
        "live_prognosen": int((archiv["herkunft"] == "live").sum()),
    }
