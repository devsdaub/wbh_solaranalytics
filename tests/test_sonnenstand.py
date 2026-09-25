from app.analytics.sonnenstand import mittagshoehe_grad, tageslaenge_stunden

import numpy as np

STUTTGART = 48.7823


def test_sommersonnenwende_hat_die_laengste_tageslaenge():
    tage = np.arange(1, 366, dtype=float)
    laengen = tageslaenge_stunden(tage, STUTTGART)
    assert 170 <= int(np.argmax(laengen)) + 1 <= 174


def test_mittagshoehe_bleibt_im_plausiblen_bereich():
    tage = np.arange(1, 366, dtype=float)
    hoehen = mittagshoehe_grad(tage, STUTTGART)
    assert 17 < hoehen.min() < 19
    assert 64 < hoehen.max() < 66
