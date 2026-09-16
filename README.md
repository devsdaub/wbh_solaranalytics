# SolarAnalytics

Kleines Projekt für ein Hoymiles Balkonkraftwerk. Zieht deine
Produktionsdaten aus der Hoymiles Cloud, holt dazu passende Wetter und
Luftqualitätsdaten von Open-Meteo und zeigt alles zusammen in einem
Dashboard mit ein paar Diagrammen.

## Voraussetzungen

Mehr als Docker wird nicht gebraucht, also Docker Desktop unter Windows
oder macOS, unter Linux Docker Engine mit dem Compose-Plugin. Python,
Postgres und die Bibliotheken stecken im Image und werden beim ersten
Start mitgebaut. Frei sein müssen die Ports 8008 für das Dashboard und
5444 für die Datenbank, sonst lassen sie sich in docker-compose.yml
ändern.

## Starten

```bash
cp .env.example .env
docker compose up --build
```

Danach läuft das Dashboard unter http://localhost:8008, die API Doku
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
    latitude: 48.7823
    longitude: 9.177
    city: "Stuttgart"
  panel:
    capacity_w: 800
    module_capacity_wp: 900
    tilt_deg: 17
    azimuth_deg: 203
  economics:
    acquisition_cost_eur: 550
    subsidy_eur: 0
    electricity_price_eur_kwh: 0.30
```

installation_date ist der Tag, an dem die Anlage ans Netz ging, danach
holt die Pipeline beim ersten Lauf alle Produktionsdaten ab diesem Datum.
latitude/longitude und city legen fest, für welchen Ort die Wetterdaten
geholt werden. capacity_w ist die Wechselrichterleistung, an der die
Einspeisung gedeckelt wird, module_capacity_wp die Modulleistung, mit der
der Effizienzquotient berechnet wird, bei mir liegt die über der
Wechselrichterleistung, weil die Module mehr könnten als der
Wechselrichter durchlässt. tilt_deg ist der Neigungswinkel des Dachs,
azimuth_deg die Ausrichtung, hier wird nordbasiert angegeben wie auf
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

25 Tests in vier Modulen, Laufzeit unter zwei Sekunden. Sie brauchen
weder Datenbank noch Netz und prüfen die Prüfschemata, die Tagesgrenzen
und Zeitumstellung, die Azimut-Umrechnung, den Parser für das
Binärformat der Hoymiles-API sowie die Erreichbarkeit der Endpunkte.

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
