from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Berlin")


def als_lokalzeit(wert: datetime | None, muster: str = "%d.%m.%Y %H:%M") -> str:
    """Rechnet einen UTC-Zeitstempel in Ortszeit um und formatiert ihn."""
    if wert is None:
        return "n. v."
    if wert.tzinfo is None:
        wert = wert.replace(tzinfo=timezone.utc)
    return wert.astimezone(LOCAL_TZ).strftime(muster)


def zeitzone_kuerzel() -> str:
    """Liefert das aktuell gültige Kürzel, also CET oder CEST."""
    return datetime.now(LOCAL_TZ).strftime("%Z")