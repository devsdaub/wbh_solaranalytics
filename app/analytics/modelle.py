import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

ZUFALLSSTARTWERT = 42

BEZEICHNUNGEN = {
    "persistenz": "Persistenz (Vortag)",
    "klimatologie": "Klimatologie (saisonal)",
    "faustregel": "Faustregel (Einstrahlung mal Ertragsquote)",
    "lineare_regression": "Lineare Regression",
    "random_forest": "Random Forest",
    "xgboost": "XGBoost",
}


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


# an fast dunklen Tagen liefe die Ertragsquote sonst gegen unendlich
MIN_GTI_KWH_M2 = 0.15


def faustregel(training: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    gti = np.clip(training["gti_kwh_m2"].to_numpy(dtype=float), MIN_GTI_KWH_M2, None)
    quote = float(np.nanmedian(training["production_kwh"].to_numpy(dtype=float) / gti))
    return quote * test["gti_kwh_m2"].to_numpy(dtype=float)


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
