import pandas as pd


def to_records(frame: pd.DataFrame) -> list[dict]:
    """Wandelt ein DataFrame in Datensätze um, pandas-Fehlwerte werden zu None."""
    records = frame.to_dict(orient="records")
    for record in records:
        for key, value in record.items():
            if pd.isna(value):
                record[key] = None
    return records