from datetime import datetime, timedelta, timezone

from app.pipeline.scheduler import ANALYSE_INTERVALL_MINUTEN, analyse_faellig


def vor(tage: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=tage)).isoformat()


def test_ohne_analyselauf_ist_die_analyse_faellig():
    assert analyse_faellig(None, ANALYSE_INTERVALL_MINUTEN)


def test_analyse_ist_erst_nach_einer_woche_wieder_faellig():
    assert not analyse_faellig(vor(1), ANALYSE_INTERVALL_MINUTEN)
    assert not analyse_faellig(vor(6.9), ANALYSE_INTERVALL_MINUTEN)
    assert analyse_faellig(vor(7.1), ANALYSE_INTERVALL_MINUTEN)
