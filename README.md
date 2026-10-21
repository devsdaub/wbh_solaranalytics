# SolarAnalytics

Kleines Projekt für ein Hoymiles Balkonkraftwerk. Zieht deine
Produktionsdaten aus der Hoymiles Cloud, holt dazu passende Wetter und
Luftqualitätsdaten von Open-Meteo und zeigt alles zusammen in einem
Dashboard mit ein paar Diagrammen.

Dazu kommt der Reiter Analytics: eine Ertragsprognose für heute und die
nächsten sechs Tage im Stil eines Wetterberichts, Prognose gegen Messung,
ein Vergleich der Verfahren, die zeitlich sauber gegeneinander bewertet
werden, und der Anteil jeder Datenquelle an der Prognose.

## Voraussetzungen

Mehr als Docker wird nicht gebraucht, also Docker Desktop unter Windows
oder macOS, unter Linux Docker Engine mit dem Compose-Plugin. Python,
Postgres und die Bibliotheken stecken im Image und werden beim ersten
Start mitgebaut. Frei sein müssen die Ports 8009 für das Dashboard und
5445 für die Datenbank, sonst lassen sie sich in docker-compose.yml
ändern.

## Starten

```bash
cp .env.example .env
docker compose up --build
```

Danach läuft das Dashboard unter http://localhost:8009, die API Doku
unter /docs. Der erste Start dauert etwas länger, weil das Image gebaut
und die Postgres-Datenbank neu angelegt wird, danach reicht
`docker compose up` ohne `--build`.

Der `cp` Befehl ist wichtig, ohne ihn gibt es keine .env und
docker compose bricht beim Start ab, weil DB_PASSWORD fehlt. Die .env
selbst steht in der .gitignore und wird nie committet, jeder legt sich
seine eigene an. Drin steht nur eine Zeile:

```
DB_PASSWORD=changeme
```

Das Passwort kann man so lassen oder ändern, es wird beim ersten Start
in docker-compose.yml an zwei Stellen eingesetzt: als Passwort für den
Postgres-Container und als Teil der DATABASE_URL, mit der sich die App
bei der Datenbank anmeldet. Beides zieht sich denselben Wert aus der
.env, deshalb reicht es, ihn nur an einer Stelle zu ändern.

Ändert man das Passwort nachträglich, wenn die Datenbank schon einmal
mit dem alten Wert angelegt wurde, reicht ein Neustart nicht, Postgres
merkt sich das alte Passwort im Volume. Dann entweder das alte Passwort
wieder eintragen oder einmal `docker compose down -v` machen, das löscht
aber auch alle bisherigen Daten.

## Eigene Anlage eintragen

Die Daten zur eigenen Anlage stehen in config/plant.yaml: Standort,
Ausrichtung des Dachs, Modulleistung und ein paar Kennzahlen zur
Anschaffung. Ohne Anpassung rechnet die Pipeline mit
meinen Werten, für eine andere Anlage müssen die hier stimmen, sonst
passt vor allem die Einstrahlung nicht zum eigenen Dach.

So sieht die Datei bei mir aus:

```yaml
plant:
  name: "Kleines Kraftwerk"
  installation_date: "2025-04-26"
  location:
    latitude: 48.75
    longitude: 9.17
    city: "Stuttgart-Degerloch"
  panel:
    capacity_w: 800
    module_capacity_wp: 900
    tilt_deg: 72
    azimuth_deg: 208
  frueher:
    - bis: "2026-02-21"
      city: "Stuttgart"
      latitude: 48.7823
      longitude: 9.177
      azimuth_deg: 203
  uebergang:
    von: "2026-02-22"
    bis: "2026-03-08"
  economics:
    acquisition_cost_eur: 550
    subsidy_eur: 0
    electricity_price_eur_kwh: 0.30
```

location und panel beschreiben den aktuellen Standort. Ist die Anlage
umgezogen, stehen frühere Standorte unter frueher, jeweils mit dem
letzten Tag, an dem sie galten. Wetter, Satellit und Vorhersagearchiv
werden dann für jeden Zeitraum mit den Koordinaten und der Ausrichtung
des damaligen Standorts abgerufen, und die Analyse bekommt die Nummer
des Standorts als Merkmal. Die Tage unter uebergang bleiben in der
Auswertung außen vor, bei mir hing die Anlage nach dem Umzug zwei
Wochen provisorisch. Ohne Umzug fallen beide Abschnitte einfach weg.

installation_date ist der Tag, an dem die Anlage ans Netz ging, danach
holt die Pipeline beim ersten Lauf alle Produktionsdaten ab diesem Datum.
latitude/longitude und city legen fest, für welchen Ort die Wetterdaten
geholt werden. capacity_w ist die Wechselrichterleistung, an der die
Einspeisung gedeckelt wird, module_capacity_wp die Modulleistung, mit der
der Effizienzquotient berechnet wird, bei mir liegt die über der
Wechselrichterleistung, weil die Module mehr könnten als der
Wechselrichter durchlässt. tilt_deg ist der Neigungswinkel der Module
gegen die Waagerechte, 0 wäre flach liegend und 90 senkrecht, ein
Balkongeländer liegt also eher bei 70 bis 90. azimuth_deg die Ausrichtung, hier wird nordbasiert angegeben wie auf
einem Kompass, 180 wäre Süden. Die Werte unter economics werden in die
Datenbank übernommen, ausgewertet werden sie bisher nicht. Eine
Wirtschaftlichkeitsrechnung gehört bewusst nicht zum Umfang.

Für den automatischen Abruf der Hoymiles Daten config/hoymiles_auth.yaml
anlegen (Vorlage liegt als hoymiles_auth.example.yaml daneben) und dort
Zugangsdaten und Anlagen-ID vom S-Miles-Cloud-Konto eintragen:

```yaml
hoymiles_auth:
  username: "dein.name@example.com"
  password: "dein-passwort"
  station_id: "1234567"
  base_url: "https://neapi.hoymiles.com"
```

username und password sind die Zugangsdaten, mit denen man sich auch in
der S-Miles-App oder auf global.hoymiles.com anmeldet. station_id findet
man am einfachsten in der S-Miles-App: Station auswählen, unter "Mehr"
bzw. den Stationsdetails auf "Info" gehen, dort steht die Stations-ID.
Alternativ steht sie in der Browser-URL, wenn man die Anlage im
Web-Portal öffnet. base_url ist bei allen gleich, das ist einfach die
feste Adresse der Hoymiles-API und kein individueller Wert pro Account,
die Zeile kann also unverändert so übernommen werden. Die Datei landet
nicht im Git, echte Zugangsdaten gehören da rein, nicht ins Beispiel
oben. Ohne diese Datei läuft alles andere trotzdem, nur die automatische
Anbindung fehlt dann. Alternativ lässt sich der CSV-Export aus dem
Hoymiles-Portal unter /settings hochladen.

Scheduler-Intervall und welche Datenquellen aktiv sind, lässt sich auch
direkt unter /settings einstellen, landet dann in den gleichen YAML
Dateien.

## Was es macht

In einem einstellbaren Intervall, voreingestellt sind 20 Minuten, holt
die Pipeline die Tagesproduktion aus der Hoymiles Cloud sowie
Einstrahlung, Temperatur und Feinstaubwerte von Open-Meteo. Daraus
entstehen Tageswerte und der Effizienzquotient, die das Dashboard
anzeigt. Fehlende Wetterdaten für ältere Tage werden automatisch
nachgeladen. Unter /settings lässt sich der Lauf auch von Hand anstoßen,
dort steht auch die Historie der bisherigen Läufe.

Die Quellen im Einzelnen, alle frei und ohne Konto:

| Quelle | Endpunkt | Wofür |
|---|---|---|
| Wetter im Rückblick | Open-Meteo Historical Forecast API, Modell `icon_d2` | Einstrahlung auf die Modulfläche, Temperatur, Wolken, Sicht, Sonnenscheindauer. Die ersten Stunden jedes ICON-D2-Laufs, näher an der Wirklichkeit als das IFS-Archiv |
| Luftqualität | Open-Meteo Air Quality API | Saharastaub, PM10, Aerosole |
| Satellit | Open-Meteo Satellite API, `eumetsat_sarah3` | gemessene Einstrahlung auf die Modulfläche, rund zwei Tage verzögert |
| Vorhersagearchiv | Open-Meteo Previous Runs API, `icon_seamless` | was 1 bis 6 Tage vorher für jede Stunde vorhergesagt war |
| Vorhersage | Open-Meteo Forecast API, `icon_seamless` | Wetter für heute und die nächsten sechs Tage |

## Prognose und Analyse

Die Prognose rechnet die vorhergesagte Einstrahlung auf die Modulfläche
mal den Median der Ertragsquote der letzten 14 Messtage am selben
Standort. Die Ertragsquote ist der Tagesertrag geteilt durch die am
Vortag dafür vorhergesagte Einstrahlung. Die Spanne um jede Prognose ist
das 10. und 90. Perzentil der Abweichungen in kWh der letzten 60 Tage
mit gleichem Vorlauf. Jeden Abend ab 20 Uhr schreibt die Pipeline die
Prognose für die nächsten sechs Tage fest, für die Zeit davor trägt sie
aus dem Vorhersagearchiv nach, was am jeweiligen Stichtag prognostiziert
worden wäre. Daraus entstehen die Vergleiche Prognose gegen Messung.

Das Wettersymbol im Wetterbericht richtet sich nach dem Anteil der
Sonnenstunden und der Regenmenge, nicht nach dem WMO-Tagescode, der das
schlechteste Wetter des Tages meldet. Die Symbole sind die Meteocons von
Bas Milius (https://github.com/basmilius/meteocons, MIT-Lizenz), die
Lizenz liegt in app/static/icons/meteocons.

Der Analyselauf startet von selbst, sobald der letzte älter als eine
Woche ist, oder über „Analyse jetzt neu rechnen“ unter /settings bzw.
`POST /api/analytics/train`, und dauert einige Minuten. Er bewertet
Persistenz, Klimatologie, eine feste und eine nachgeführte Faustregel
sowie lineare Regression, Random Forest und XGBoost, jeweils mit und
ohne Nachführung, in zwei zeitlichen Schemata. Dazu kommen Ablation,
Permutation Importance, Fehler je Wetterlage und je Jahreszeit. Für die
Prognose setzt er das genaueste Verfahren ein, umgestellt wird aber nur,
wenn es laut Diebold-Mariano-Test signifikant besser ist als das
bisherige. Die Ergebnisse landen in analytics_artifacts/ergebnisse.json, die Prognosen
je Tag in prognosen_s2.csv und die Abbildungen mit 300 dpi unter
analytics_artifacts/abbildungen. Herauskopieren:

```bash
docker compose cp app:/app/analytics_artifacts ./ergebnisse
```

## Ohne Hoymiles-Zugang

Auch ohne config/hoymiles_auth.yaml startet alles und die Pipeline läuft
durch. Die Hoymiles-Quelle meldet dann im Betriebsprotokoll
"uebersprungen", Wetter und Luftqualität werden trotzdem geholt. Das
Dashboard zeigt entsprechend Einstrahlung und Wetter, bei Produktion und
Effizienzquotient steht "n. v.". Produktionsdaten lassen sich in diesem
Fall über den CSV-Export aus dem Hoymiles-Portal unter /settings
hochladen.

Im Ordner beispieldaten liegt dafür ein echter Export im aktuellen Format des Energy-Reports. 
Nach dem Import einmal "Fehlende Wetterdaten nachladen" drücken, dann liegen zu den
Produktionstagen auch Einstrahlung und Effizienzquotient vor.

## Tests

```bash
docker compose exec app python -m pytest -q
```

84 Tests in zwölf Modulen, Laufzeit rund fünf Sekunden. Sie prüfen die
Prüfschemata, Tagesgrenzen und Zeitumstellung, die Azimut-Umrechnung,
den Parser für das Binärformat der Hoymiles-API, die Standortgeschichte,
den Merkmalsbau, die Referenz- und Lernverfahren, dass kein Zeitfenster
in die Zukunft sieht, die Spanne der Prognose, die Auswahlregel, den
wöchentlichen Analyselauf und die Erreichbarkeit der Seiten und
Endpunkte. Die Tests der Endpunkte brauchen die laufende Datenbank.

Dieselben Tests laufen bei jedem Push auf main in GitHub Actions gegen
eine leere Datenbank, erst danach wird das Image gebaut.

## Auf dem NAS betreiben

GitHub Actions baut bei jedem Push auf main das Image
`ghcr.io/devsdaub/wbh-solaranalytics` und legt es in der GitHub
Container Registry ab. Das NAS zieht nur dieses Image und baut nichts
selbst. Compose-Datei, Variablen und Anleitung samt Datenübernahme vom PC
liegen in deploy/nas.

## Stoppen und zurücksetzen

```bash
docker compose down
```

Das hält die Container an, die Daten bleiben im Volume erhalten. Soll
auch der Datenbestand weg:

```bash
docker compose down -v
```

Beim nächsten Start legt die Anwendung das Schema neu an und holt die
Historie ab dem installation_date erneut.
