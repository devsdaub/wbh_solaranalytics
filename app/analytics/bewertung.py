import logging

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.inspection import permutation_importance
from sklearn.model_selection import TimeSeriesSplit

from app.analytics.merkmale import ANLAGE, MERKMALSGRUPPEN, ZIELGROESSE, ergaenze_wetterlagen
from app.analytics.modelle import (
    LERNVERFAHREN,
    REFERENZEN,
    baue_modelle,
    faustregel,
    faustregel_nachgefuehrt,
    klimatologie,
    nachfuehren,
    persistenz,
)

logger = logging.getLogger(__name__)

ANZAHL_FALTUNGEN = 5
MIN_TRAININGSTAGE_S2 = 150

JAHRESZEITEN = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Frühling", 4: "Frühling",
                5: "Frühling", 6: "Sommer", 7: "Sommer", 8: "Sommer", 9: "Herbst",
                10: "Herbst", 11: "Herbst"}

NACHGEFUEHRTE_LERNVERFAHREN = [f"{name}_nachgefuehrt" for name in LERNVERFAHREN]


def schema_s1(frame: pd.DataFrame) -> list[tuple[np.ndarray, np.ndarray]]:
    """Fünf aufeinanderfolgende Zeitfenster, das Training wächst von Fenster zu Fenster."""
    # bei kurzen Reihen weniger Faltungen, sonst wird das erste Fenster zu klein
    anzahl = min(ANZAHL_FALTUNGEN, max(2, len(frame) // 60))
    return list(TimeSeriesSplit(n_splits=anzahl).split(frame))


def schema_s2(frame: pd.DataFrame) -> list[tuple[np.ndarray, np.ndarray]]:
    """Jeder Monat einmal Testmonat, trainiert auf allen Tagen davor."""
    monat = pd.to_datetime(frame["date"]).dt.to_period("M").to_numpy()
    faltungen = []
    for periode in sorted(set(monat)):
        test = np.flatnonzero(monat == periode)
        training = np.arange(test[0])
        if len(training) >= MIN_TRAININGSTAGE_S2:
            faltungen.append((training, test))
    return faltungen


def schemata(frame: pd.DataFrame) -> dict[str, list]:
    return {"S1": schema_s1(frame), "S2": schema_s2(frame)}


def kennzahlen(ist: np.ndarray, prognose: np.ndarray) -> dict:
    gueltig = ~(np.isnan(ist) | np.isnan(prognose))
    if gueltig.sum() == 0:
        return {"mae": None, "rmse": None, "nmae_prozent": None, "bias_prozent": None, "n": 0}
    fehler = prognose[gueltig] - ist[gueltig]
    mae = float(np.mean(np.abs(fehler)))
    return {
        "mae": round(mae, 3),
        "rmse": round(float(np.sqrt(np.mean(fehler ** 2))), 3),
        "nmae_prozent": round(100.0 * mae / float(np.mean(ist[gueltig])), 1),
        "bias_prozent": round(float(100.0 * (prognose[gueltig].sum() / ist[gueltig].sum() - 1.0)), 1),
        "n": int(gueltig.sum()),
    }


def dm_test(ist: np.ndarray, prognose_a: np.ndarray, prognose_b: np.ndarray) -> dict:
    """Diebold-Mariano-Test auf die Differenz der absoluten Fehler, Vorlauf ein Tag."""
    gueltig = ~(np.isnan(ist) | np.isnan(prognose_a) | np.isnan(prognose_b))
    d = np.abs(prognose_a[gueltig] - ist[gueltig]) - np.abs(prognose_b[gueltig] - ist[gueltig])
    if len(d) < 10 or np.var(d, ddof=1) == 0:
        return {"statistik": None, "p_wert": None, "n": int(len(d))}
    statistik = float(np.mean(d) / np.sqrt(np.var(d, ddof=1) / len(d)))
    return {
        "statistik": round(statistik, 2),
        "p_wert": round(float(2.0 * (1.0 - stats.norm.cdf(abs(statistik)))), 4),
        "n": int(len(d)),
    }


def berechne_prognosen(frame: pd.DataFrame, merkmale: list[str], faltungen: list,
                       gti_spalte: str = "gti_kwh_m2", abstand: int = 1) -> dict[str, np.ndarray]:
    """Alle Verfahren über dieselben Faltungen, jeweils nur mit Trainingstagen gelernt."""
    X = frame[merkmale].astype(float)
    y = frame[ZIELGROESSE].to_numpy(dtype=float)
    namen = REFERENZEN + LERNVERFAHREN
    prognosen = {name: np.full(len(frame), np.nan) for name in namen}

    # braucht kein Training, nur die Tage vor dem Zieltag
    nachgefuehrt = faustregel_nachgefuehrt(frame, gti_spalte, abstand=abstand)

    for training_idx, test_idx in faltungen:
        training, test = frame.iloc[training_idx], frame.iloc[test_idx]
        prognosen["persistenz"][test_idx] = persistenz(training, test)
        prognosen["klimatologie"][test_idx] = klimatologie(training, test)
        prognosen["faustregel"][test_idx] = faustregel(training, test, gti_spalte)
        prognosen["faustregel_nachgefuehrt"][test_idx] = nachgefuehrt[test_idx]

        for name, pipeline in baue_modelle().items():
            pipeline.fit(X.iloc[training_idx], y[training_idx])
            prognosen[name][test_idx] = np.clip(pipeline.predict(X.iloc[test_idx]), 0, None)

    for name in LERNVERFAHREN:
        prognosen[f"{name}_nachgefuehrt"] = nachfuehren(frame, prognosen[name], abstand=abstand)
    return prognosen


def gemeinsame_tage(frame: pd.DataFrame, prognosen: dict[str, np.ndarray]) -> np.ndarray:
    """Nur Tage, für die jedes Verfahren eine Prognose hat, sonst wären die Fehler nicht vergleichbar."""
    maske = frame[ZIELGROESSE].notna().to_numpy()
    for werte in prognosen.values():
        maske &= ~np.isnan(werte)
    return maske


def fehler_je_jahreszeit(frame: pd.DataFrame, prognose: np.ndarray, maske: np.ndarray) -> dict:
    zeit = pd.to_datetime(frame["date"]).dt.month.map(JAHRESZEITEN).to_numpy()
    ist = frame[ZIELGROESSE].to_numpy(dtype=float)
    ergebnis = {}
    for name in ("Winter", "Frühling", "Sommer", "Herbst"):
        auswahl = maske & (zeit == name)
        werte = kennzahlen(ist[auswahl], prognose[auswahl])
        werte["mittlerer_ertrag"] = round(float(ist[auswahl].mean()), 2) if auswahl.any() else None
        ergebnis[name] = werte
    return ergebnis


def vergleiche_verfahren(frame: pd.DataFrame, merkmale: list[str],
                         gti_spalte: str = "gti_kwh_m2", abstand: int = 1) -> dict:
    """Modellvergleich in beiden Bewertungsschemata, mit Skill, Jahreszeiten und Signifikanztest."""
    ist = frame[ZIELGROESSE].to_numpy(dtype=float)
    ergebnis = {"verfahren": {}, "schemata": {}, "prognosen": {}, "masken": {}}

    for schema, faltungen in schemata(frame).items():
        if not faltungen:
            continue
        prognosen = berechne_prognosen(frame, merkmale, faltungen, gti_spalte, abstand)
        maske = gemeinsame_tage(frame, prognosen)
        ergebnis["prognosen"][schema] = prognosen
        ergebnis["masken"][schema] = maske
        tage = frame.loc[maske, "date"]
        ergebnis["schemata"][schema] = {
            "faltungen": len(faltungen),
            "tage": int(maske.sum()),
            "von": str(tage.min()) if len(tage) else None,
            "bis": str(tage.max()) if len(tage) else None,
            "mittlerer_ertrag": round(float(ist[maske].mean()), 2) if maske.any() else None,
        }
        for name, werte in prognosen.items():
            eintrag = ergebnis["verfahren"].setdefault(name, {})
            eintrag[schema] = kennzahlen(ist[maske], werte[maske])

    haupt = "S2" if "S2" in ergebnis["prognosen"] else "S1"
    ergebnis["hauptschema"] = haupt
    mae = {name: werte[haupt]["mae"] for name, werte in ergebnis["verfahren"].items()}

    beste_referenz = min(REFERENZEN, key=lambda n: mae[n])
    bestes_lernverfahren = min(LERNVERFAHREN, key=lambda n: mae[n])
    bestes_nachgefuehrt = min(NACHGEFUEHRTE_LERNVERFAHREN, key=lambda n: mae[n])
    bestes = min(mae, key=mae.get)

    for name, werte in ergebnis["verfahren"].items():
        werte["skill_persistenz_prozent"] = round(100.0 * (1.0 - mae[name] / mae["persistenz"]), 1)
        werte["skill_referenz_prozent"] = round(100.0 * (1.0 - mae[name] / mae[beste_referenz]), 1)
        werte["jahreszeiten"] = fehler_je_jahreszeit(
            frame, ergebnis["prognosen"][haupt][name], ergebnis["masken"][haupt]
        )

    prognosen = ergebnis["prognosen"][haupt]
    maske = ergebnis["masken"][haupt]
    gegner = bestes_nachgefuehrt if mae[bestes_nachgefuehrt] < mae[bestes_lernverfahren] else bestes_lernverfahren
    ergebnis.update(
        beste_referenz=beste_referenz,
        bestes_lernverfahren=bestes_lernverfahren,
        bestes_nachgefuehrt=bestes_nachgefuehrt,
        bestes_verfahren=bestes,
        signifikanz={
            "verfahren_a": gegner,
            "verfahren_b": beste_referenz,
            **dm_test(ist[maske], prognosen[gegner][maske], prognosen[beste_referenz][maske]),
        },
    )
    return ergebnis


def ablationskonfigurationen() -> list[tuple[str, list[str]]]:
    alle = [s for spalten in MERKMALSGRUPPEN.values() for s in spalten]
    konfigurationen = [("alle Quellen", alle + ANLAGE)]
    for gruppe in MERKMALSGRUPPEN:
        rest = [s for g, spalten in MERKMALSGRUPPEN.items() if g != gruppe for s in spalten]
        konfigurationen.append((f"ohne {gruppe}", rest + ANLAGE))
    for gruppe, spalten in MERKMALSGRUPPEN.items():
        konfigurationen.append((f"nur {gruppe}", list(spalten) + ANLAGE))
    return konfigurationen


def fuehre_ablation_durch(frame: pd.DataFrame, modellname: str) -> list[dict]:
    """Dasselbe Lernverfahren, einmal mit allen Quellen und je einmal ohne und nur mit einer Gruppe."""
    y = frame[ZIELGROESSE].to_numpy(dtype=float)
    faltungen = schemata(frame)
    ergebnisse = []
    voll: dict[str, float] = {}

    for bezeichnung, spalten in ablationskonfigurationen():
        X = frame[spalten].astype(float)
        eintrag = {"konfiguration": bezeichnung, "anzahl_merkmale": len(spalten)}
        for schema, liste in faltungen.items():
            if not liste:
                continue
            prognose = np.full(len(frame), np.nan)
            for training_idx, test_idx in liste:
                # jedes Mal eine frische Pipeline, sonst trägt sie den vorigen Fit mit
                pipeline = baue_modelle()[modellname]
                pipeline.fit(X.iloc[training_idx], y[training_idx])
                prognose[test_idx] = np.clip(pipeline.predict(X.iloc[test_idx]), 0, None)
            werte = kennzahlen(y, prognose)
            eintrag[schema] = werte
            if bezeichnung == "alle Quellen":
                voll[schema] = werte["mae"]
            elif voll.get(schema):
                eintrag[schema]["delta_prozent"] = round(
                    100.0 * (werte["mae"] - voll[schema]) / voll[schema], 1
                )
        ergebnisse.append(eintrag)
    return ergebnisse


def berechne_importance(frame: pd.DataFrame, modellname: str, merkmale: list[str]) -> list[dict]:
    """Permutation Importance auf dem letzten Zeitfenster, also ausserhalb des Trainings."""
    X = frame[merkmale].astype(float)
    y = frame[ZIELGROESSE].to_numpy(dtype=float)
    training_idx, test_idx = schema_s1(frame)[-1]

    pipeline = baue_modelle()[modellname]
    pipeline.fit(X.iloc[training_idx], y[training_idx])

    ergebnis = permutation_importance(
        pipeline, X.iloc[test_idx], y[test_idx],
        n_repeats=15, random_state=42, scoring="neg_mean_absolute_error",
    )
    werte = [
        {
            "merkmal": name,
            "gruppe": next((g for g, s in MERKMALSGRUPPEN.items() if name in s), "anlage"),
            "beitrag_mae": round(float(ergebnis.importances_mean[i]), 4),
            "streuung": round(float(ergebnis.importances_std[i]), 4),
        }
        for i, name in enumerate(merkmale)
    ]
    return sorted(werte, key=lambda d: d["beitrag_mae"], reverse=True)


def fehler_je_wetterlage(frame: pd.DataFrame, prognose: np.ndarray, maske: np.ndarray) -> list[dict]:
    markiert = ergaenze_wetterlagen(frame).assign(prognose=prognose)[maske]

    ergebnisse = []
    for lage, gruppe in markiert.groupby("wetterlage"):
        ist = gruppe[ZIELGROESSE].to_numpy(dtype=float)
        werte = gruppe["prognose"].to_numpy(dtype=float)
        ergebnisse.append({
            "wetterlage": lage,
            "tage": int(len(gruppe)),
            "mae": kennzahlen(ist, werte)["mae"],
            "mittlerer_ertrag": round(float(ist.mean()), 2),
            # positiv bedeutet systematische Überschätzung
            "bias_kwh": round(float(np.mean(werte - ist)), 3),
        })
    return sorted(ergebnisse, key=lambda d: d["mae"] or 0, reverse=True)


def vergleiche_quellen(rueckblick: pd.DataFrame, vorhersage: pd.DataFrame) -> list[dict]:
    """Dieselbe nachgeführte Faustregel, nur die Quelle der Einstrahlung wechselt."""
    vortag = vorhersage[["date", "gti_kwh_m2"]].rename(columns={"gti_kwh_m2": "gti_vorhersage"})
    frame = rueckblick.merge(vortag, on="date", how="inner").reset_index(drop=True)
    faltungen = schema_s2(frame) or schema_s1(frame)
    test = np.zeros(len(frame), dtype=bool)
    for _, test_idx in faltungen:
        test[test_idx] = True

    varianten = [
        ("ICON-Vorhersage vom Vortag", "vorhersage", "gti_vorhersage", 2),
        ("ICON-D2-Analyse im Rückblick", "rueckblick", "gti_kwh_m2", 1),
        ("Satellit SARAH-3 im Rückblick", "rueckblick", "gti_satellit_kwh_m2", 1),
    ]
    prognosen = {name: faustregel_nachgefuehrt(frame, spalte, abstand=abstand)
                 for name, _, spalte, abstand in varianten}
    maske = test & frame[ZIELGROESSE].notna().to_numpy()
    for werte in prognosen.values():
        maske &= ~np.isnan(werte)

    ist = frame[ZIELGROESSE].to_numpy(dtype=float)
    return [
        {"quelle": name, "art": art, **kennzahlen(ist[maske], prognosen[name][maske])}
        for name, art, _, _ in varianten
    ]
