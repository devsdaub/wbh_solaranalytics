from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

import pandas as pd


class SourceAdapter(ABC):
    """Quellen, die Daten für einen frei wählbaren Zeitraum liefern.
    """

    name: str

    @abstractmethod
    def fetch(self, start: date, end: date) -> pd.DataFrame:
        """Holt Rohdaten der Quelle für den angegebenen Zeitraum.
        """


class FileAdapter(ABC):
    """Quellen, die aus einer hochgeladenen Datei gelesen werden.
    """

    name: str

    @abstractmethod
    def parse(self, path: Path, plant_id: int) -> pd.DataFrame:
        """Liest eine Datei ein, bereinigt sie und gibt sie validiert zurück."""