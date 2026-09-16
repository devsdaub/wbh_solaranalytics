import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import RedirectResponse

from app.pipeline.ingestion import import_energy_report

router = APIRouter(prefix="/api", tags=["Upload"])

UPLOAD_DIR = Path("/app/uploads")


def _speichern(file: UploadFile) -> Path:
    """Legt die hochgeladene Datei im Upload-Verzeichnis ab."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Es werden nur CSV-Dateien akzeptiert.")

    # .name verwirft Pfadanteile im Dateinamen (Path Traversal)
    target = UPLOAD_DIR / Path(file.filename).name
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    with target.open("wb") as ziel:
        shutil.copyfileobj(file.file, ziel)
    return target


@router.post("/upload/energy")
def upload_energy_report(file: UploadFile) -> dict:
    """Nimmt einen Hoymiles-Energy-Report entgegen und importiert ihn."""
    target = _speichern(file)
    try:
        return import_energy_report(target)
    except ValueError as fehler:
        raise HTTPException(422, str(fehler)) from fehler


@router.post("/upload/energy/form")
def upload_energy_report_form(file: UploadFile) -> RedirectResponse:
    """Verarbeitet den Upload aus dem Formular der Settings-Seite."""
    target = _speichern(file)
    try:
        ergebnis = import_energy_report(target)
    except ValueError:
        return RedirectResponse("/settings?gespeichert=upload_fehler", status_code=303)

    return RedirectResponse(
        f"/settings?gespeichert=upload&zeilen={ergebnis['datensaetze']}",
        status_code=303,
    )