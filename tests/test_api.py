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
    assert "SolarPipeline" in antwort.text


def test_zeitreihe_hat_gleich_lange_reihen():
    """Chart.js ordnet Werte über die Position zu. Wäre eine Reihe kürzer,
    verschöben sich alle folgenden Werte um einen Tag."""
    daten = client.get("/api/data/daily?days=30").json()

    laengen = {len(daten[reihe]) for reihe in
               ("labels", "produktion", "einstrahlung", "eq")}
    assert len(laengen) == 1
