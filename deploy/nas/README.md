# SolarAnalytics auf dem NAS

Für das UGREEN-NAS mit UGOS Pro und Portainer, gleicher Weg wie bei MingHub. Auf dem NAS
wird nichts gebaut und kein Repository ausgecheckt. Es zieht nur das fertige Image.

```
Push auf main → GitHub Actions testet, baut und pusht → ghcr.io/devsdaub/wbh-solaranalytics
                                                                │
                                    Portainer → Stacks → solaranalytics → Update the stack
                                                                │
                                                     NAS zieht das neue Image
```

Jeder Push trägt zwei Tags: `latest` und `sha-xxxxxxx` mit dem Kurz-Hash des Commits.

## Erstinstallation

1. **Ordner anlegen:** UGOS → Dateien → `docker` → Unterordner `solaranalytics` mit
   Unterordner `config`.
2. **Konfiguration mitnehmen:** die Dateien aus `config/` auf dem PC in diesen Ordner
   kopieren, also `plant.yaml`, `scheduler.yaml`, `sources.yaml` und `hoymiles_auth.yaml`.
   Die Zugangsdaten stehen weder im Git noch im Image, nur so kommt die Hoymiles-Anbindung
   aufs NAS. Bleibt der Ordner leer, legt der Container beim Start die Standarddateien
   hinein und läuft ohne Hoymiles.
3. **Zugang zur Registry:** Das Paket einmal öffentlich stellen, dann braucht das NAS keine
   Anmeldung: GitHub → Packages → `wbh-solaranalytics` → Package settings → Danger Zone →
   Change visibility → Public. Ein öffentliches Repository reicht dafür nicht, die
   Sichtbarkeit des Pakets wird getrennt eingestellt. Das Image enthält keine
   Zugangsdaten. Bleibt das Paket privat, geht es mit dem Token mit `read:packages`, der
   auch für MingHub gilt, in Portainer unter Registries oder per SSH mit
   `docker login ghcr.io -u devsdaub`.
4. **Stack anlegen:** Portainer → Stacks → Add stack → Name `solaranalytics` → Web editor
   → Inhalt von `docker-compose.yml` aus diesem Ordner einfügen → Environment variables →
   „Advanced mode“ → Inhalt von `stack.env.example` einfügen, `DB_PASSWORD` ersetzen →
   Deploy the stack.
5. **Aufrufen:** `http://<ip-des-nas>:8009` von jedem Gerät im Heimnetz. Keine
   Portfreigabe im Router einrichten.

Ohne Portainer geht es auch in UGOS Pro unter Docker → Projekt → Erstellen. Dann die Werte
aus `stack.env.example` direkt in die Compose-Datei schreiben. Wichtig ist die Datei aus
diesem Ordner, nicht die `docker-compose.yml` im Hauptordner: Die ist für den PC und will
das Image selbst bauen, auf dem NAS endet das mit „open Dockerfile: no such file or
directory“.

## Daten vom PC übernehmen

Meist nicht nötig. Messwerte und Wetter holt die Pipeline auf dem NAS selbst nach, das
Prognosearchiv rechnet sie für vergangene Tage im Rückblick nach. Auf einer frischen
Instanz fehlen nur die Prognosen, die eine andere Instanz abends live festgeschrieben hat.
Beim Umzug am 21.10.2026 waren das die sechs Zeilen vom 14.10. aus dem Vorbau, eingespielt
mit einer einzelnen SQL-Datei statt eines ganzen Abzugs.

Soll doch die ganze Datenbank umziehen, auf dem PC im Repository-Ordner:

```bash
docker compose exec -T db pg_dump -U solar -d solaranalytics --clean --if-exists -f /tmp/solaranalytics.sql
```

```bash
docker compose cp db:/tmp/solaranalytics.sql D:/solaranalytics.sql
```

Die Datei nach `/volume1/docker/solaranalytics/` kopieren. Auf dem NAS per SSH die App
kurz anhalten, einspielen und wieder starten (Namen bei Bedarf mit `docker ps` prüfen):

```bash
docker stop solaranalytics-app-1
```

```bash
docker exec -i solaranalytics-db-1 psql -q -U solar -d solaranalytics < /volume1/docker/solaranalytics/solaranalytics.sql
```

```bash
docker start solaranalytics-app-1
```

Die Analyse fehlt auf einem frischen NAS. Der wöchentliche Lauf merkt das und startet fünf
Minuten nach dem Start von selbst, sonst unter Einstellungen „Analyse jetzt neu rechnen“.

## Update nach einem Push

GitHub → Actions abwarten, bis der Lauf grün ist. Dann Portainer → Stacks →
`solaranalytics` → Editor → „Update the stack“ mit „Re-pull image and redeploy“.
Datenbank, Konfiguration und Analyse liegen in Volumes und im config-Ordner und bleiben
erhalten. Neue Spalten legt die App beim Start selbst an (`app/migration.py`).

## Rollback

`SOLARANALYTICS_TAG` in den Stack-Variablen auf den vorherigen `sha-xxxxxxx` setzen und den
Stack neu bereitstellen. Das betrifft nur den Code, die Datenbank bleibt, wie sie ist.

## PC und NAS gleichzeitig

Beide Instanzen haben eigene Datenbanken und stören sich nicht. Für die Arbeit sollte am
Ende eine Instanz zählen. Das NAS läuft auch abends, wenn der PC aus ist, und verpasst
damit keine festgeschriebene Prognose mehr.
