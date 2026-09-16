from calendar import monthrange
from datetime import date

from sqlalchemy import select

from app.database import SessionLocal
from app.models import DailyFact

MONATSNAMEN = [
    "Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dez",
]

STUFEN = 5


def baue_heatmap(plant_id: int) -> list[dict]:
    """Erzeugt die Monatszeilen für die Kalender-Heatmap."""
    with SessionLocal() as session:
        zeilen = session.execute(
            select(DailyFact.date, DailyFact.production_kwh)
            .where(DailyFact.plant_id == plant_id)
            .where(DailyFact.production_kwh.is_not(None))
            .order_by(DailyFact.date)
        ).all()

    if not zeilen:
        return []

    werte = {zeile.date: zeile.production_kwh for zeile in zeilen}
    hoechstwert = max(werte.values())

    erster, letzter = min(werte), max(werte)
    monate = []

    jahr, monat = erster.year, erster.month
    while (jahr, monat) <= (letzter.year, letzter.month):
        tage_im_monat = monthrange(jahr, monat)[1]
        tage = []

        for tag in range(1, 32):
            if tag > tage_im_monat:
                tage.append({"vorhanden": False})
                continue

            wert = werte.get(date(jahr, monat, tag))
            tage.append({
                "vorhanden": True,
                "wert": wert,
                "stufe": _stufe(wert, hoechstwert),
                "datum": date(jahr, monat, tag).strftime("%d.%m.%Y"),
            })

        monate.append({
            "label": f"{MONATSNAMEN[monat - 1]} {jahr}",
            "tage": tage,
        })

        monat += 1
        if monat > 12:
            monat, jahr = 1, jahr + 1

    return monate


def _stufe(wert: float | None, hoechstwert: float) -> int:
    """Ordnet einen Tageswert einer von fünf Farbstufen zu."""
    if wert is None or hoechstwert <= 0:
        return 0

    stufe = int(wert / hoechstwert * STUFEN) + 1
    return min(stufe, STUFEN)