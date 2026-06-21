#!/bin/bash
# =============================================================================
# Dimplex System M – UHI Firewall remote umschalten
# =============================================================================
# Setzt in /usr/local/uhi/lib/firewall/index.js
#   -P INPUT DROP   → Firewall AN  (Standard nach Update)
#   -P INPUT ACCEPT → Firewall AUS (API von außen erreichbar)
#
# Voraussetzungen auf dem Ziel-Raspberry:
#   - SSH-Zugang (Passwort ODER Public-Key)
#   - sudo-Rechte für den verwendeten User
#
# Verwendung:
#   chmod +x dimplex_uhi_firewall.sh
#   ./dimplex_uhi_firewall.sh                        # interaktiv
#   ./dimplex_uhi_firewall.sh -h 192.168.1.100 open  # direkt öffnen
#   ./dimplex_uhi_firewall.sh -h 192.168.1.100 close # direkt schließen
#   ./dimplex_uhi_firewall.sh -h 192.168.1.100 status
# =============================================================================

set -euo pipefail

# ---------- Defaults ----------------------------------------------------------
SSH_USER="pi"
SSH_HOST=""
SSH_PORT=22
SSH_KEY=""          # leer = Passwort-Auth
ACTION=""           # open | close | status
REMOTE_FILE="/usr/local/uhi/lib/firewall/index.js"

# ---------- Farben ------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ---------- Hilfe -------------------------------------------------------------
usage() {
    echo -e "${BOLD}Verwendung:${NC}"
    echo "  $0 [OPTIONEN] [open|close|status]"
    echo ""
    echo -e "${BOLD}Optionen:${NC}"
    echo "  -h HOST        IP oder Hostname der Wärmepumpe (Raspberry)"
    echo "  -u USER        SSH-Benutzer (Standard: pi)"
    echo "  -p PORT        SSH-Port     (Standard: 22)"
    echo "  -i KEY_FILE    Pfad zum privaten SSH-Schlüssel (optional)"
    echo ""
    echo -e "${BOLD}Aktionen:${NC}"
    echo "  open    Firewall AUS → API von außen erreichbar  (-P INPUT ACCEPT)"
    echo "  close   Firewall AN  → API gesperrt              (-P INPUT DROP)"
    echo "  status  Aktuellen Wert in der Datei anzeigen"
    echo ""
    echo -e "${BOLD}Beispiele:${NC}"
    echo "  $0 -h 192.168.1.100 open"
    echo "  $0 -h 192.168.1.100 -u admin -i ~/.ssh/id_rsa close"
    echo "  $0 -h 192.168.1.100 status"
    exit 0
}

# ---------- Argumente parsen --------------------------------------------------
while getopts ":h:u:p:i:" opt; do
    case $opt in
        h) SSH_HOST="$OPTARG" ;;
        u) SSH_USER="$OPTARG" ;;
        p) SSH_PORT="$OPTARG" ;;
        i) SSH_KEY="$OPTARG" ;;
        \?) echo -e "${RED}Unbekannte Option: -$OPTARG${NC}" >&2; usage ;;
    esac
done
shift $((OPTIND - 1))

# Verbleibendes Argument = Aktion
[[ $# -gt 0 ]] && ACTION="$1"

# ---------- Interaktiver Modus ------------------------------------------------
if [[ -z "$SSH_HOST" ]]; then
    echo -e "${CYAN}${BOLD}=== Dimplex System M – UHI Firewall ===${NC}"
    echo ""
    read -rp "  Raspberry IP / Hostname: " SSH_HOST
    read -rp "  SSH-Benutzer [$SSH_USER]: " input
    [[ -n "$input" ]] && SSH_USER="$input"
    read -rp "  SSH-Port [$SSH_PORT]: " input
    [[ -n "$input" ]] && SSH_PORT="$input"
    read -rp "  SSH-Key-Datei (leer = Passwort): " SSH_KEY
    echo ""
fi

if [[ -z "$ACTION" ]]; then
    echo -e "${CYAN}${BOLD}=== Aktion wählen ===${NC}"
    echo "  1) open   – Firewall AUS (API erreichbar)"
    echo "  2) close  – Firewall AN  (API gesperrt)"
    echo "  3) status – Aktuellen Zustand anzeigen"
    echo ""
    read -rp "  Auswahl [1/2/3]: " choice
    case "$choice" in
        1) ACTION="open" ;;
        2) ACTION="close" ;;
        3) ACTION="status" ;;
        *) echo -e "${RED}Ungültige Auswahl.${NC}"; exit 1 ;;
    esac
fi

# ---------- Validierung -------------------------------------------------------
if [[ -z "$SSH_HOST" ]]; then
    echo -e "${RED}Fehler: Kein Host angegeben.${NC}"; exit 1
fi

if [[ ! "$ACTION" =~ ^(open|close|status)$ ]]; then
    echo -e "${RED}Fehler: Unbekannte Aktion '$ACTION'. Erlaubt: open, close, status${NC}"
    exit 1
fi

# ---------- SSH-Basiskommando zusammenbauen -----------------------------------
SSH_OPTS=(-o StrictHostKeyChecking=accept-new
           -o ConnectTimeout=10
           -p "$SSH_PORT")

if [[ -n "$SSH_KEY" ]]; then
    SSH_OPTS+=(-i "$SSH_KEY")
fi

SSH_CMD=(ssh "${SSH_OPTS[@]}" "${SSH_USER}@${SSH_HOST}")

echo ""
echo -e "${CYAN}Verbinde mit ${BOLD}${SSH_USER}@${SSH_HOST}:${SSH_PORT}${NC}${CYAN} …${NC}"

# ---------- Remote-Skript -----------------------------------------------------
REMOTE_SCRIPT=$(cat <<'REMOTE'
set -euo pipefail

REMOTE_FILE="/usr/local/uhi/lib/firewall/index.js"
ACTION="__ACTION__"

# Prüfen ob Datei existiert
if [[ ! -f "$REMOTE_FILE" ]]; then
    echo "FEHLER: Datei nicht gefunden: $REMOTE_FILE"
    exit 1
fi

# Aktuellen Wert lesen
# grep -F = Fixed-String (kein Regex), -- = Ende der Optionen (schützt vor führendem -)
if grep -qF -- "-P INPUT ACCEPT" "$REMOTE_FILE"; then
    CURRENT="open"
elif grep -qF -- "-P INPUT DROP" "$REMOTE_FILE"; then
    CURRENT="closed"
else
    echo "WARNUNG: Keiner der erwarteten Werte gefunden – Dateiinhalt ggf. geändert."
    CURRENT="unknown"
fi

if [[ "$ACTION" == "status" ]]; then
    echo "STATUS:$CURRENT"
    echo "---"
    grep -nF -- "INPUT" "$REMOTE_FILE" || echo "(keine INPUT-Zeile gefunden)"
    exit 0
fi

if [[ "$ACTION" == "open" ]]; then
    NEW_FROM="-P INPUT DROP"
    NEW_TO="-P INPUT ACCEPT"
    LABEL="OFFEN (API erreichbar)"
fi

if [[ "$ACTION" == "close" ]]; then
    NEW_FROM="-P INPUT ACCEPT"
    NEW_TO="-P INPUT DROP"
    LABEL="GESPERRT (Firewall aktiv)"
fi

# Backup anlegen
BACKUP="${REMOTE_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
sudo cp "$REMOTE_FILE" "$BACKUP"
echo "BACKUP:$BACKUP"

# Wert ersetzen
sudo sed -i "s|${NEW_FROM}|${NEW_TO}|g" "$REMOTE_FILE"

# Verifizieren
if grep -qF -- "$NEW_TO" "$REMOTE_FILE"; then
    echo "OK:$LABEL"
else
    echo "FEHLER: Ersetzung fehlgeschlagen – Backup: $BACKUP"
    sudo cp "$BACKUP" "$REMOTE_FILE"
    exit 1
fi

# UHI-Dienst neu starten (falls systemd-Unit vorhanden)
if sudo systemctl list-units --type=service 2>/dev/null | grep -qi -- "uhi"; then
    UHI_SERVICE=$(sudo systemctl list-units --type=service 2>/dev/null \
                  | grep -i -- "uhi" | awk '{print $1}' | head -1)
    sudo systemctl restart "$UHI_SERVICE" 2>/dev/null \
        && echo "RESTART:$UHI_SERVICE" \
        || echo "HINWEIS: Dienst-Neustart fehlgeschlagen – ggf. manuell neu starten"
else
    echo "HINWEIS: Kein UHI-Systemd-Dienst gefunden. Neustart der WP empfohlen."
fi
REMOTE
)

# Aktion ins Skript einsetzen
REMOTE_SCRIPT="${REMOTE_SCRIPT//__ACTION__/$ACTION}"

# ---------- Ausführen ---------------------------------------------------------
echo ""
OUTPUT=$("${SSH_CMD[@]}" "bash -s" <<< "$REMOTE_SCRIPT" 2>&1) || {
    echo -e "${RED}SSH-Verbindung fehlgeschlagen.${NC}"
    echo "$OUTPUT"
    exit 1
}

# ---------- Ausgabe interpretieren --------------------------------------------
echo ""
echo -e "${CYAN}${BOLD}=== Ergebnis ===${NC}"
while IFS= read -r line; do
    case "$line" in
        STATUS:open)    echo -e "  Aktueller Zustand: ${GREEN}${BOLD}OFFEN${NC} (API erreichbar, Firewall inaktiv)" ;;
        STATUS:closed)  echo -e "  Aktueller Zustand: ${RED}${BOLD}GESPERRT${NC} (Firewall aktiv)" ;;
        STATUS:unknown) echo -e "  Aktueller Zustand: ${YELLOW}UNBEKANNT${NC}" ;;
        STATUS:*)       echo -e "  Status: ${line#STATUS:}" ;;
        OK:*)           echo -e "  ${GREEN}✓ Erfolgreich gesetzt:${NC} ${line#OK:}" ;;
        BACKUP:*)       echo -e "  ${YELLOW}↩ Backup:${NC} ${line#BACKUP:}" ;;
        RESTART:*)      echo -e "  ${CYAN}↺ Dienst neu gestartet:${NC} ${line#RESTART:}" ;;
        FEHLER:*)       echo -e "  ${RED}✗ Fehler:${NC} ${line#FEHLER:}" ;;
        WARNUNG:*|HINWEIS:*) echo -e "  ${YELLOW}⚠ ${line}${NC}" ;;
        ---)            echo -e "  ${CYAN}──────────────────────────────${NC}" ;;
        *)              echo "  $line" ;;
    esac
done <<< "$OUTPUT"

echo ""
echo -e "${CYAN}${BOLD}=== Fertig ===${NC}"
echo ""
