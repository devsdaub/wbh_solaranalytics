from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_meldet_die_datenbank():
    antwort = client.get("/health")

    assert antwort.status_code == 200
    assert antwort.json()["database"] == "ok"


def test_dashboard_rendert():
    antwort = client.get("/")

    assert antwort.status_code == 200
    assert "SolarAnalytics" in antwort.text


def test_zeitreihe_hat_gleich_lange_reihen():
    """Chart.js ordnet Werte über die Position zu. Wäre eine Reihe kürzer,
    verschöben sich alle folgenden Werte um einen Tag."""
    daten = client.get("/api/data/daily?days=30").json()

    laengen = {len(daten[reihe]) for reihe in
               ("labels", "produktion", "einstrahlung", "eq")}
    assert len(laengen) == 1


def test_analytics_seite_rendert_mit_reitern():
    antwort = client.get("/analytics")

    assert antwort.status_code == 200
    assert 'id="analytics"' in antwort.text
    assert "/static/js/analytics.js" in antwort.text
    assert 'href="/analytics" class="aktiv"' in antwort.text


def test_analysestatus_meldet_den_lauf():
    daten = client.get("/api/analytics/status").json()

    assert set(daten) >= {"lauf", "trainiert"}
    assert daten["lauf"]["laeuft"] in (True, False)


def test_verlauf_hat_alle_vorlaeufe_je_tag():
    tage = client.get("/api/analytics/verlauf?tage=20").json()["tage"]

    assert len(tage) == 20
    assert {"ist", "p1", "u1", "o1", "p6"} <= set(tage[0])


def test_einstellungen_zeigen_die_karte_analyse():
    antwort = client.get("/settings")

    assert antwort.status_code == 200
    assert "Analyse jetzt neu rechnen" in antwort.text
    assert "Jede Woche automatisch neu rechnen" in antwort.text
