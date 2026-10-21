import logging
import time
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.analytics.abbildungen import erzeuge_abbildungen
from app.analytics.artefakte import ARTEFAKTE, speichere_ergebnisse, speichere_modell
from app.analytics.bewertung import (
    berechne_importance,
    fehler_je_wetterlage,
    fuehre_ablation_durch,
    vergleiche_quellen,
    vergleiche_verfahren,
)
from app.analytics.merkmale import (
    ALLE_MERKMALE,
    GRUPPENNAMEN,
    MERKMALSGRUPPEN,
    VORHERSAGE_MERKMALE,
    ZIELGROESSE,
    baue_merkmalsmatrix,
    baue_vorhersagematrix,
)
from app.analytics.modelle import (
    BEZEICHNUNGEN,
    FENSTER_NACHFUEHRUNG_TAGE,
    GRENZEN_NACHFUEHRUNG,
    MIN_TAGE_NACHFUEHRUNG,
    baue_modelle,
)
from app.analytics.prognose import VERFAHREN, guete, pflege_prognosearchiv

logger = logging.getLogger(__name__)

MIN_TAGE = 90

LAGEN = {
    "rueckblick": {
        "titel": "Wetter im Nachhinein (ICON-D2-Analyse)",
        "merkmale": ALLE_MERKMALE,
        "abstand": 1,
    },
    "vorhersage": {
        "titel": "Prognose für morgen (ICON-Vorhersage vom Vortag)",
        "merkmale": VORHERSAGE_MERKMALE,
        "abstand": 2,
    },
}


def _nachfuehrfaktor(frame: pd.DataFrame, prognose: np.ndarray) -> float:
    """Verhältnis von Messung zu Prognose der letzten bewerteten Tage, wie in der Auswertung."""
    ist = frame[ZIELGROESSE].to_numpy(dtype=float)
    letzte = np.flatnonzero(~np.isnan(prognose) & ~np.isnan(ist))[-FENSTER_NACHFUEHRUNG_TAGE:]
    if len(letzte) < MIN_TAGE_NACHFUEHRUNG:
        return 1.0
    return float(np.clip(ist[letzte].sum() / prognose[letzte].sum(), *GRENZEN_NACHFUEHRUNG))


def _prognosetabelle(frames: dict, vergleiche: dict) -> pd.DataFrame:
    """Alle Prognosen aus S2 je Tag, als Grundlage für Abbildungen und eigene Nachrechnungen."""
    teile = []
    for lage, vergleich in vergleiche.items():
        schema = vergleich["hauptschema"]
        frame = frames[lage]
        tabelle = pd.DataFrame({"lage": lage, "date": frame["date"], "ist": frame[ZIELGROESSE],
                                "bewertet": vergleich["masken"][schema]})
        for name, werte in vergleich["prognosen"][schema].items():
            tabelle[name] = np.round(werte, 3)
        teile.append(tabelle)
    return pd.concat(teile, ignore_index=True)


def trainiere_und_bewerte(session: Session, plant_id: int = 1) -> dict:
    start = time.time()
    frames = {
        "rueckblick": baue_merkmalsmatrix(session, plant_id),
        "vorhersage": baue_vorhersagematrix(session, plant_id, vorlauf=1),
    }
    for lage, frame in frames.items():
        if len(frame) < MIN_TAGE:
            raise ValueError(f"{lage}: nur {len(frame)} auswertbare Tage, mindestens {MIN_TAGE} noetig")

    vergleiche = {}
    for lage, einstellung in LAGEN.items():
        logger.info("Analyse: Modellvergleich %s", lage)
        vergleiche[lage] = vergleiche_verfahren(
            frames[lage], einstellung["merkmale"], abstand=einstellung["abstand"]
        )

    rueckblick, vorhersage = frames["rueckblick"], frames["vorhersage"]
    bestes = vergleiche["rueckblick"]["bestes_lernverfahren"]

    logger.info("Analyse: Ablation mit %s", bestes)
    ablation = fuehre_ablation_durch(rueckblick, bestes)

    logger.info("Analyse: Permutation Importance")
    importance = berechne_importance(rueckblick, bestes, ALLE_MERKMALE)

    logger.info("Analyse: Fehler nach Wetterlagen und Quellenvergleich")
    wetterlagen = {}
    for lage, verfahren in (("rueckblick", vergleiche["rueckblick"]["bestes_verfahren"]),
                            ("vorhersage", VERFAHREN)):
        vergleich = vergleiche[lage]
        schema = vergleich["hauptschema"]
        # die Wetterlage beschreibt das tatsächliche Wetter, also immer aus dem Rückblick
        tatsaechlich = frames[lage][["date"]].merge(rueckblick, on="date", how="left")
        wetterlagen[lage] = {
            "verfahren": verfahren,
            "werte": fehler_je_wetterlage(
                tatsaechlich, vergleich["prognosen"][schema][verfahren], vergleich["masken"][schema]
            ),
        }
    quellen = vergleiche_quellen(rueckblick, vorhersage)

    # für die Live-Prognose das beste Lernverfahren auf den Vorhersagen aller Tage
    vergleich = vergleiche["vorhersage"]
    gewaehlt = min((vergleich["bestes_lernverfahren"], vergleich["bestes_nachgefuehrt"]),
                   key=lambda n: vergleich["verfahren"][n][vergleich["hauptschema"]]["mae"])
    grundform = gewaehlt.removesuffix("_nachgefuehrt")
    faktor = 1.0
    if gewaehlt != grundform:
        faktor = _nachfuehrfaktor(vorhersage, vergleich["prognosen"][vergleich["hauptschema"]][grundform])
    endmodell = baue_modelle()[grundform]
    endmodell.fit(vorhersage[VORHERSAGE_MERKMALE].astype(float), vorhersage[ZIELGROESSE].astype(float))
    speichere_modell({"modell": endmodell, "merkmale": VORHERSAGE_MERKMALE, "name": gewaehlt,
                      "faktor": faktor, "trainiert_am": datetime.now(timezone.utc).isoformat()})

    logger.info("Analyse: Prognosearchiv und Fehler nach Vorlauf")
    pflege_prognosearchiv(plant_id)
    ab = vergleich["schemata"].get(vergleich["hauptschema"], {}).get("von")
    archiv = guete(plant_id, ab=date.fromisoformat(ab) if ab else None)

    _prognosetabelle(frames, vergleiche).to_csv(ARTEFAKTE / "prognosen_s2.csv", index=False)

    ergebnis = {
        "trainiert_am": datetime.now(timezone.utc).isoformat(),
        "dauer_sekunden": round(time.time() - start),
        "daten": {
            "tage": int(len(rueckblick)),
            "von": str(rueckblick["date"].min()),
            "bis": str(rueckblick["date"].max()),
            "ausfalltage": rueckblick.attrs.get("ausfalltage"),
            "uebergangstage": rueckblick.attrs.get("uebergangstage"),
            "mittlerer_ertrag_kwh": round(float(rueckblick[ZIELGROESSE].mean()), 2),
        },
        "bezeichnungen": BEZEICHNUNGEN,
        "gruppen": GRUPPENNAMEN,
        "merkmalsgruppen": MERKMALSGRUPPEN,
        "lagen": {
            lage: {
                "titel": LAGEN[lage]["titel"],
                "merkmale": LAGEN[lage]["merkmale"],
                "abstand_tage": LAGEN[lage]["abstand"],
                **{k: v for k, v in vergleich.items() if k not in ("prognosen", "masken")},
            }
            for lage, vergleich in vergleiche.items()
        },
        "ablation": {"modell": bestes, "konfigurationen": ablation},
        "importance": {"modell": bestes, "werte": importance},
        "wetterlagen": wetterlagen,
        "quellen": quellen,
        "horizont": archiv["horizont"],
        "horizont_jahreszeiten": archiv["jahreszeiten"],
        "eingesetzt": {"verfahren": VERFAHREN, "lernverfahren": gewaehlt, "faktor": round(faktor, 3)},
    }
    speichere_ergebnisse(ergebnis)
    logger.info("Analyse: Ergebnisse gespeichert nach %s s", ergebnis["dauer_sekunden"])

    # Abbildungen für die Thesis immer aus genau diesem Lauf
    try:
        erzeuge_abbildungen()
    except Exception:
        logger.exception("Abbildungen nicht erzeugt")
    return ergebnis
