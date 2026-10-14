import logging

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from app.analytics.artefakte import ABBILDUNGEN, ARTEFAKTE, lade_ergebnisse  # noqa: E402

logger = logging.getLogger(__name__)

DPI = 300
GRUEN, DUNKEL, BLAU, ORANGE, GRAU = "#22c55e", "#1b3a5c", "#60a5fa", "#f59e0b", "#cbd5e1"
REFERENZEN = {"persistenz", "klimatologie", "faustregel", "faustregel_nachgefuehrt"}
KURZTITEL = {"rueckblick": "Wetter im Nachhinein", "vorhersage": "Prognose für morgen"}
GRUPPENFARBE = {"wetter": BLAU, "satellit": DUNKEL, "luftqualitaet": ORANGE, "sonnenstand": GRUEN, "anlage": GRAU}

plt.rcParams.update({
    "font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#e8edf3", "axes.axisbelow": True,
})


def _speichern(figur, name: str) -> str:
    ABBILDUNGEN.mkdir(parents=True, exist_ok=True)
    pfad = ABBILDUNGEN / f"{name}.png"
    figur.tight_layout()
    figur.savefig(pfad, dpi=DPI)
    plt.close(figur)
    return str(pfad)


def _komma(wert: float, stellen: int = 2) -> str:
    return f"{wert:.{stellen}f}".replace(".", ",")


def modellvergleich(e: dict) -> str:
    figur, achsen = plt.subplots(2, 1, figsize=(6.5, 7.2), sharex=True)
    for achse, lage in zip(achsen, ("rueckblick", "vorhersage")):
        inhalt = e["lagen"][lage]
        schema = inhalt["hauptschema"]
        liste = sorted(inhalt["verfahren"].items(), key=lambda x: x[1][schema]["mae"], reverse=True)
        namen = [e["bezeichnungen"][n] for n, _ in liste]
        werte = [w[schema]["mae"] for _, w in liste]
        farben = [ORANGE if n in REFERENZEN else GRUEN for n, _ in liste]
        achse.barh(namen, werte, color=farben)
        for i, wert in enumerate(werte):
            achse.text(wert + 0.01, i, _komma(wert, 3), va="center", fontsize=7)
        achse.set_title(KURZTITEL[lage], fontsize=9)
        achse.set_xlabel(f"MAE in kWh, Bewertung {schema}")
    return _speichern(figur, "modellvergleich")


def ablation(e: dict) -> str:
    konfigurationen = [k for k in e["ablation"]["konfigurationen"] if k["konfiguration"].startswith("ohne")]
    gruppen = [k["konfiguration"].removeprefix("ohne ") for k in konfigurationen]
    figur, achse = plt.subplots(figsize=(6.5, 3.0))
    achse.barh([f"ohne {e['gruppen'][g]}" for g in gruppen],
               [k["S2"]["delta_prozent"] for k in konfigurationen],
               color=[GRUPPENFARBE[g] for g in gruppen])
    achse.axvline(0, color="#64748b", linewidth=0.8)
    achse.set_xlabel("Änderung des MAE gegenüber allen Quellen in Prozent (S2)")
    achse.set_title(f"Ablation mit {e['bezeichnungen'][e['ablation']['modell']]}, Wetter im Nachhinein", fontsize=9)
    return _speichern(figur, "ablation")


def importance(e: dict) -> str:
    werte = e["importance"]["werte"][:12][::-1]
    figur, achse = plt.subplots(figsize=(6.5, 3.8))
    achse.barh([w["merkmal"] for w in werte], [w["beitrag_mae"] for w in werte],
               xerr=[w["streuung"] for w in werte], color=[GRUPPENFARBE[w["gruppe"]] for w in werte],
               error_kw={"elinewidth": 0.8, "ecolor": "#64748b"})
    achse.set_xlabel("Anstieg des MAE beim Vertauschen in kWh")
    achse.set_title(f"Permutation Importance, {e['bezeichnungen'][e['importance']['modell']]}", fontsize=9)
    return _speichern(figur, "importance")


def horizont(e: dict) -> str:
    werte = e["horizont"]
    klima = e["lagen"]["vorhersage"]["verfahren"]["klimatologie"]["S2"]["mae"]
    figur, achse = plt.subplots(figsize=(6.0, 3.2))
    achse.bar([str(h["vorlauf"]) for h in werte], [h["mae"] for h in werte], color=GRUEN, label="nachgeführte Faustregel")
    achse.axhline(klima, color=ORANGE, linestyle="--", linewidth=1.2, label="Klimatologie, ohne Wetterbericht")
    for i, h in enumerate(werte):
        achse.text(i, h["mae"] + 0.015, _komma(h["mae"]), ha="center", fontsize=7)
    achse.set_xlabel("Vorlauf in Tagen")
    achse.set_ylabel("MAE in kWh")
    achse.set_ylim(0, klima * 1.3)
    achse.legend(frameon=False, fontsize=8, loc="upper left", ncol=2)
    return _speichern(figur, "fehler_nach_vorlauf")


def quellen(e: dict) -> str:
    werte = e["quellen"]
    figur, achse = plt.subplots(figsize=(6.0, 2.4))
    achse.barh([q["quelle"] for q in werte][::-1], [q["mae"] for q in werte][::-1],
               color=[GRUEN if q["art"] == "vorhersage" else BLAU for q in werte][::-1])
    achse.set_xlabel("MAE der nachgeführten Faustregel in kWh")
    return _speichern(figur, "quelle_der_einstrahlung")


def jahreszeiten(e: dict) -> str:
    lage = e["lagen"]["vorhersage"]
    namen = ["Winter", "Frühling", "Sommer", "Herbst"]
    auswahl = [lage["beste_referenz"], lage["bestes_nachgefuehrt"], lage["bestes_lernverfahren"]]
    farben = [DUNKEL, GRUEN, GRAU]
    figur, achse = plt.subplots(figsize=(6.5, 3.2))
    breite = 0.26
    for i, schluessel in enumerate(auswahl):
        werte = [lage["verfahren"][schluessel]["jahreszeiten"][z]["mae"] or 0 for z in namen]
        achse.bar([x + (i - 1) * breite for x in range(4)], werte, width=breite,
                  color=farben[i], label=e["bezeichnungen"][schluessel])
    achse.set_xticks(range(4), namen)
    achse.set_ylabel("MAE in kWh")
    achse.legend(frameon=False, fontsize=7)
    return _speichern(figur, "fehler_nach_jahreszeit")


def streuung() -> str | None:
    pfad = ARTEFAKTE / "prognosen_s2.csv"
    if not pfad.exists():
        return None
    tabelle = pd.read_csv(pfad)
    tabelle = tabelle[(tabelle["lage"] == "vorhersage") & tabelle["bewertet"]]
    grenze = float(max(tabelle["ist"].max(), tabelle["faustregel_nachgefuehrt"].max())) * 1.05
    figur, achse = plt.subplots(figsize=(4.2, 4.0))
    achse.scatter(tabelle["ist"], tabelle["faustregel_nachgefuehrt"], s=8, color=GRUEN, alpha=0.7)
    achse.plot([0, grenze], [0, grenze], color=DUNKEL, linestyle="--", linewidth=0.8)
    achse.set_xlim(0, grenze)
    achse.set_ylim(0, grenze)
    achse.set_xlabel("gemessen in kWh")
    achse.set_ylabel("Prognose für morgen in kWh")
    return _speichern(figur, "prognose_ueber_messung")


def erzeuge_abbildungen() -> list[str]:
    e = lade_ergebnisse()
    if e is None:
        raise FileNotFoundError("Noch kein Analyselauf vorhanden")
    pfade = [modellvergleich(e), ablation(e), importance(e), horizont(e), quellen(e), jahreszeiten(e), streuung()]
    pfade = [p for p in pfade if p]
    logger.info("Abbildungen: %s Dateien in %s", len(pfade), ABBILDUNGEN)
    return pfade


if __name__ == "__main__":
    for datei in erzeuge_abbildungen():
        print(datei)
