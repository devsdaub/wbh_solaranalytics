from datetime import date

import pandas as pd

from app.adapters.open_meteo_vorhersage import OpenMeteoVorhersagearchivAdapter
from app.config import PlantSettings, SourceSettings
from app.standorte import ist_uebergang, standort_am, standorte_im_zeitraum


def anlage() -> PlantSettings:
    return PlantSettings.model_validate({
        "name": "Test",
        "installation_date": "2025-04-26",
        "location": {"latitude": 48.75, "longitude": 9.17, "city": "Neu"},
        "panel": {"capacity_w": 800, "module_capacity_wp": 900, "tilt_deg": 72, "azimuth_deg": 208},
        "frueher": [{"bis": "2026-02-21", "city": "Alt", "latitude": 48.78,
                     "longitude": 9.18, "azimuth_deg": 203}],
        "uebergang": {"von": "2026-02-22", "bis": "2026-03-08"},
        "economics": {"acquisition_cost_eur": 550, "subsidy_eur": 0,
                      "electricity_price_eur_kwh": 0.3},
    })


def test_standort_wechselt_am_tag_nach_dem_letzten_gueltigen():
    assert standort_am(anlage(), date(2026, 2, 21)).azimuth_deg == 203
    assert standort_am(anlage(), date(2026, 2, 22)).azimuth_deg == 208


def test_frueherer_standort_erbt_die_neigung():
    assert standort_am(anlage(), date(2025, 6, 1)).tilt_deg == 72


def test_zeitraum_ueber_den_umzug_wird_geteilt():
    abschnitte = standorte_im_zeitraum(anlage(), date(2026, 2, 1), date(2026, 3, 1))

    assert [(s.nummer, von, bis) for s, von, bis in abschnitte] == [
        (0, date(2026, 2, 1), date(2026, 2, 21)),
        (1, date(2026, 2, 22), date(2026, 3, 1)),
    ]


def test_zeitraum_an_einem_standort_bleibt_ganz():
    abschnitte = standorte_im_zeitraum(anlage(), date(2026, 5, 1), date(2026, 5, 31))

    assert len(abschnitte) == 1


def test_uebergangszeit_mit_beiden_grenzen():
    assert ist_uebergang(anlage(), date(2026, 2, 22))
    assert ist_uebergang(anlage(), date(2026, 3, 8))
    assert not ist_uebergang(anlage(), date(2026, 3, 9))


def test_vorhersagearchiv_wird_je_vorlauf_lang():
    quelle = SourceSettings(enabled=True, url="https://example.test", default_days_back=1,
                            max_vorlauf=2, variables=["global_tilted_irradiance"])
    adapter = OpenMeteoVorhersagearchivAdapter(anlage(), quelle, plant_id=1)
    breit = pd.DataFrame({
        "time": pd.date_range("2026-05-01", periods=3, freq="h", tz="UTC"),
        "global_tilted_irradiance_previous_day1": [1.0, 2.0, 3.0],
        "global_tilted_irradiance_previous_day2": [4.0, 5.0, 6.0],
    })

    lang = adapter.aufbereiten(breit)

    assert adapter.abgefragte_variablen() == [
        "global_tilted_irradiance_previous_day1", "global_tilted_irradiance_previous_day2",
    ]
    assert list(lang["vorlauf"]) == [1, 1, 1, 2, 2, 2]
    assert list(lang["gti"]) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
