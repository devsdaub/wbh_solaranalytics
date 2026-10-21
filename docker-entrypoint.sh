#!/bin/sh
set -e

# Fehlende Konfigurationsdateien aus der Vorlage im Image ergänzen, vorhandene bleiben unangetastet
mkdir -p /app/config
for datei in /app/config_vorlage/*; do
    ziel="/app/config/$(basename "$datei")"
    [ -e "$ziel" ] || cp "$datei" "$ziel"
done

exec "$@"
