import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

ZUFALLSSTARTWERT = 42

REFERENZEN = ["persistenz", "klimatologie", "faustregel", "faustregel_nachgefuehrt"]
LERNVERFAHREN = ["lineare_regression", "random_forest", "xgboost"]

BEZEICHNUNGEN = {
    "persistenz": "Persistenz (wie am Vortag)",
    "klimatologie": "Klimatologie (Mittel der Jahreszeit)",
    "faustregel": "Faustregel, feste Quote je Standort und Sonnenhöhe",
    "faustregel_nachgefuehrt": "Faustregel, Quote der letzten 14 Tage",
    "lineare_regression": "Lineare Regression",
    "random_forest": "Random Forest",
    "xgboost": "XGBoost",
    "lineare_regression_nachgefuehrt": "Lineare Regression mit Nachführung",
    "random_forest_nachgefuehrt": "Random Forest mit Nachführung",
    "xgboost_nachgefuehrt": "XGBoost mit Nachführung",
}

# an fast dunklen Tagen liefe die Ertragsquote sonst gegen unendlich
MIN_GTI_KWH_M2 = 0.15

STUFEN_MITTAGSHOEHE = [30.0, 45.0]
MIN_TAGE_JE_STUFE = 10

FENSTER_QUOTE_TAGE = 14

FENSTER_NACHFUEHRUNG_TAGE = 30
MIN_TAGE_NACHFUEHRUNG = 7
GRENZEN_NACHFUEHRUNG = (0.6, 1.6)


def persistenz(training: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    verlauf = pd.concat([training, test]).sort_values("date").reset_index(drop=True)
    vortag = dict(zip(verlauf["date"], verlauf["production_kwh"].shift(1)))
    return np.array([vortag[tag] for tag in test["date"]], dtype=float)


def klimatologie(training: pd.DataFrame, test: pd.DataFrame,
                 fenster_tage: int = 15) -> np.ndarray:
    tag_im_jahr = pd.to_datetime(training["date"]).dt.dayofyear.to_numpy()
    werte = training["production_kwh"].to_numpy(dtype=float)
    gesamtmittel = float(np.nanmean(werte))

    prognosen = []
    for ziel in pd.to_datetime(test["date"]).dt.dayofyear:
        abstand = np.abs(tag_im_jahr - ziel)
        abstand = np.minimum(abstand, 365 - abstand)
        treffer = abstand <= fenster_tage
        prognosen.append(float(np.nanmean(werte[treffer])) if treffer.any()
                         else gesamtmittel)
    return np.array(prognosen, dtype=float)


def ertragsquote(frame: pd.DataFrame, gti_spalte: str = "gti_kwh_m2") -> np.ndarray:
    gti = np.clip(frame[gti_spalte].to_numpy(dtype=float), MIN_GTI_KWH_M2, None)
    return frame["production_kwh"].to_numpy(dtype=float) / gti


def _spalte_oder_null(frame: pd.DataFrame, spalte: str) -> np.ndarray:
    if spalte in frame:
        return frame[spalte].to_numpy(dtype=float)
    return np.zeros(len(frame))


def faustregel(training: pd.DataFrame, test: pd.DataFrame,
               gti_spalte: str = "gti_kwh_m2") -> np.ndarray:
    """Median der Ertragsquote im Training, getrennt nach Standort und Stufe der Mittagshöhe."""
    quote = ertragsquote(training, gti_spalte)
    ort_training = _spalte_oder_null(training, "standort")
    ort_test = _spalte_oder_null(test, "standort")
    stufe_training = np.digitize(_spalte_oder_null(training, "mittagshoehe_grad"), STUFEN_MITTAGSHOEHE)
    stufe_test = np.digitize(_spalte_oder_null(test, "mittagshoehe_grad"), STUFEN_MITTAGSHOEHE)
    gti_test = test[gti_spalte].to_numpy(dtype=float)

    prognose = np.empty(len(test))
    for i in range(len(test)):
        auswahl = ort_training == ort_test[i]
        if not auswahl.any():
            auswahl = np.ones(len(training), dtype=bool)
        gleiche_stufe = auswahl & (stufe_training == stufe_test[i])
        if gleiche_stufe.sum() >= MIN_TAGE_JE_STUFE:
            auswahl = gleiche_stufe
        prognose[i] = np.nanmedian(quote[auswahl]) * gti_test[i]
    return prognose


def gleitende_quote(tage: np.ndarray, quote: np.ndarray, ort: np.ndarray,
                    bis: np.datetime64, ziel_ort: float,
                    fenster: int = FENSTER_QUOTE_TAGE) -> float:
    """Median der Ertragsquote der letzten Messtage bis einschliesslich bis, am selben Standort."""
    frueher = ~np.isnan(quote) & (tage <= bis)
    hier = np.flatnonzero(frueher & (ort == ziel_ort))
    if not len(hier):
        # am ersten Tag nach einem Umzug fehlt noch eigene Geschichte
        hier = np.flatnonzero(frueher)
    return float(np.median(quote[hier[-fenster:]])) if len(hier) else float("nan")


def faustregel_nachgefuehrt(frame: pd.DataFrame, gti_spalte: str = "gti_kwh_m2",
                            fenster: int = FENSTER_QUOTE_TAGE, abstand: int = 1,
                            gti_ziel_spalte: str | None = None) -> np.ndarray:
    """Einstrahlung mal Median der Ertragsquote der letzten Messtage am selben Standort."""
    # abstand: Tage zwischen letztem verwendetem Messtag und Zieltag
    tage = pd.to_datetime(frame["date"]).to_numpy(dtype="datetime64[D]")
    quote = ertragsquote(frame, gti_spalte)
    gti = frame[gti_ziel_spalte or gti_spalte].to_numpy(dtype=float)
    ort = _spalte_oder_null(frame, "standort")

    prognose = np.full(len(frame), np.nan)
    for i in range(len(frame)):
        bis = tage[i] - np.timedelta64(abstand, "D")
        prognose[i] = gleitende_quote(tage, quote, ort, bis, ort[i], fenster) * gti[i]
    return prognose


def nachfuehren(frame: pd.DataFrame, prognose: np.ndarray,
                fenster: int = FENSTER_NACHFUEHRUNG_TAGE, abstand: int = 1) -> np.ndarray:
    """Skaliert jede Prognose mit dem Verhältnis von Messung zu Prognose der letzten Tage."""
    # prognose enthält nur Werte, die ausserhalb des Trainings entstanden sind
    tage = pd.to_datetime(frame["date"]).to_numpy(dtype="datetime64[D]")
    ertrag = frame["production_kwh"].to_numpy(dtype=float)
    ort = _spalte_oder_null(frame, "standort")
    vorhanden = ~np.isnan(prognose) & ~np.isnan(ertrag)

    ergebnis = prognose.copy()
    for i in np.flatnonzero(~np.isnan(prognose)):
        frueher = np.flatnonzero(
            vorhanden & (ort == ort[i]) & (tage <= tage[i] - np.timedelta64(abstand, "D"))
        )[-fenster:]
        if len(frueher) >= MIN_TAGE_NACHFUEHRUNG:
            faktor = ertrag[frueher].sum() / max(prognose[frueher].sum(), 1e-6)
            ergebnis[i] = prognose[i] * np.clip(faktor, *GRENZEN_NACHFUEHRUNG)
    return ergebnis


def baue_modelle() -> dict[str, Pipeline]:
    return {
        "lineare_regression": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("skalierung", StandardScaler()),
            ("modell", LinearRegression()),
        ]),
        "random_forest": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("modell", RandomForestRegressor(
                n_estimators=400,
                min_samples_leaf=5,
                random_state=ZUFALLSSTARTWERT,
                n_jobs=-1,
            )),
        ]),
        "xgboost": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("modell", XGBRegressor(
                n_estimators=600,
                learning_rate=0.03,
                max_depth=4,
                subsample=0.9,
                colsample_bytree=0.9,
                reg_lambda=1.0,
                random_state=ZUFALLSSTARTWERT,
                n_jobs=-1,
            )),
        ]),
    }
