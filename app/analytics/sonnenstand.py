import numpy as np
import pandas as pd


def deklination_grad(tag_im_jahr: np.ndarray) -> np.ndarray:
    return 23.45 * np.sin(np.deg2rad(360.0 * (284 + tag_im_jahr) / 365.0))


def mittagshoehe_grad(tag_im_jahr: np.ndarray, breite_grad: float) -> np.ndarray:
    return 90.0 - np.abs(breite_grad - deklination_grad(tag_im_jahr))


def tageslaenge_stunden(tag_im_jahr: np.ndarray, breite_grad: float) -> np.ndarray:
    deklination = np.deg2rad(deklination_grad(tag_im_jahr))
    breite = np.deg2rad(breite_grad)
    # ausserhalb von [-1, 1] liegt Polartag oder Polarnacht
    cos_h = np.clip(-np.tan(breite) * np.tan(deklination), -1.0, 1.0)
    return 2.0 * np.rad2deg(np.arccos(cos_h)) / 15.0


def sonnenstand_merkmale(datum: pd.Series, breite_grad: float) -> pd.DataFrame:
    doy = pd.to_datetime(datum).dt.dayofyear.to_numpy(dtype=float)
    return pd.DataFrame({
        "tageslaenge_h": tageslaenge_stunden(doy, breite_grad),
        "mittagshoehe_grad": mittagshoehe_grad(doy, breite_grad),
        "jahrestag_sin": np.sin(2.0 * np.pi * doy / 365.25),
        "jahrestag_cos": np.cos(2.0 * np.pi * doy / 365.25),
    }, index=datum.index)
