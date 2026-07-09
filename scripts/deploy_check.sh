#!/usr/bin/env bash
# deploy_check.sh — garde-fou avant tout restart de service Flask sur ce VPS.
# Usage : deploy_check.sh <service_name>
#
# Remplace un "sudo systemctl restart <service>" direct par :
#   1. verification syntaxe Python du fichier principal
#   2. detection d'une perte de code anormale vs le dernier commit git (>20% de lignes en moins)
#   3. signalement (non bloquant) des fichiers non commites dans le dossier du service
#   4. restart + health check HTTP
#   5. rollback automatique (git checkout HEAD -- <dossier du service>) + restart si le health check echoue
#   6. alerte email en cas de rollback
set -uo pipefail

SERVICE="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="/home/ubuntu/automations/logs"
LOG="$LOG_DIR/deploy_check.log"
mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

usage() {
  echo "Usage: $0 <service_name>"
  echo "Services connus : chloe-dashboard factures-app liste-attente recurrence-calendly export-eleves sophie-dashboard"
}

if [ -z "$SERVICE" ]; then usage; exit 1; fi

# --- Config par service : REPO | SUBDIR (sous-dossier du service, "." si racine du repo) | FILE (fichier principal) | PORT | AUTH (USER_ENV:PASS_ENV, vide si pas de login) ---
case "$SERVICE" in
  chloe-dashboard)      REPO=/home/ubuntu/automations;       SUBDIR=chloe-dashboard;        FILE=chloe-dashboard/app.py;      PORT=5005; AUTH="DASHBOARD_USER:DASHBOARD_PASSWORD" ;;
  factures-app)         REPO=/home/ubuntu/automations;       SUBDIR=factures;               FILE=factures/app.py;             PORT=5004; AUTH="" ;;
  liste-attente)        REPO=/home/ubuntu/automations;       SUBDIR=liste_attente;          FILE=liste_attente/app.py;        PORT=5002; AUTH="" ;;
  recurrence-calendly)  REPO=/home/ubuntu/automations;       SUBDIR=recurrence_calendly;    FILE=recurrence_calendly/app.py;  PORT=5007; AUTH="" ;;
  export-eleves)        REPO=/home/ubuntu/automations;       SUBDIR=export_excel;           FILE=export_excel/app.py;         PORT=5003; AUTH="" ;;
  sophie-dashboard)     REPO=/home/ubuntu/sophie-dashboard;  SUBDIR=.;                      FILE=app.py;                       PORT=5006; AUTH="SOPHIE_DASHBOARD_USER:SOPHIE_DASHBOARD_PASSWORD" ;;
  *) log "ERREUR: service inconnu '$SERVICE'"; usage; exit 1 ;;
esac

ENV_FILE="/home/ubuntu/automations/.env"
get_env_var() {
  local key="$1"
  [ -f "$ENV_FILE" ] || return
  sed -n -E "s/^${key}=//p" "$ENV_FILE" | head -1 | sed -E 's/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/'
}

# Health check : authentifie (login + cookie) si AUTH est defini, sinon requete anonyme.
# Important : une requete anonyme sur "/" ne traverse jamais un @login_required (redirect 302
# avant le render), donc ne detecte pas un template casse cote page authentifiee (cause du 2026-07-08).
health_check() {
  local port="$1"
  if [ -n "$AUTH" ]; then
    local user_var="${AUTH%%:*}" pass_var="${AUTH##*:}"
    local login_user login_pass jar
    login_user=$(get_env_var "$user_var")
    login_pass=$(get_env_var "$pass_var")
    jar=$(mktemp)
    curl -s -c "$jar" --max-time 5 -d "username=${login_user}&password=${login_pass}" "http://127.0.0.1:${port}/login" -o /dev/null
    curl -s -b "$jar" -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:${port}/"
    rm -f "$jar"
  else
    curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:${port}/"
  fi
}

ABS_FILE="$REPO/$FILE"
[ -f "$ABS_FILE" ] || { log "ERREUR: fichier introuvable: $ABS_FILE"; exit 1; }

# Interpreteur Python pour la verification de syntaxe : venv du service si present, sinon python3 systeme
VENV_CANDIDATES=(
  "$REPO/$(dirname "$FILE")/venv/bin/python"
  "$REPO/venv/bin/python"
)
PYBIN="python3"
for c in "${VENV_CANDIDATES[@]}"; do
  if [ -x "$c" ]; then PYBIN="$c"; break; fi
done

send_alert() {
  local subject="$1" body="$2"
  python3 "$SCRIPT_DIR/send_alert.py" "$subject" "$body" >>"$LOG" 2>&1
}

log "=== deploy_check.sh $SERVICE ==="

# 1. Syntaxe Python
if ! "$PYBIN" -m py_compile "$ABS_FILE" 2>>"$LOG"; then
  log "ABORT: erreur de syntaxe dans $FILE - restart annule, service non touche"
  send_alert "[VPS] Restart $SERVICE annule - erreur de syntaxe" "py_compile a echoue sur $ABS_FILE. Restart annule, service $SERVICE non touche (toujours sur l'ancienne version en memoire)."
  exit 1
fi

cd "$REPO" || exit 1
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # 2. Diff de taille vs dernier commit
  NEW_LINES=$(wc -l < "$ABS_FILE")
  OLD_LINES=$(git show "HEAD:$FILE" 2>/dev/null | wc -l)
  if [ "${OLD_LINES:-0}" -gt 0 ]; then
    THRESHOLD=$(( OLD_LINES * 80 / 100 ))
    if [ "$NEW_LINES" -lt "$THRESHOLD" ]; then
      log "ABORT: $FILE est passe de $OLD_LINES a $NEW_LINES lignes (perte > 20% vs HEAD) - restart annule, service non touche"
      send_alert "[VPS] Restart $SERVICE annule - perte de code suspecte" "$FILE : $OLD_LINES -> $NEW_LINES lignes (vs dernier commit HEAD). Restart annule, service $SERVICE non touche. Verifier avec: git diff HEAD -- $FILE"
      exit 1
    fi
  else
    log "INFO: $FILE absent de HEAD (nouveau fichier non commite) - verification de taille ignoree"
  fi

  # 3. git status (non bloquant, juste signalement)
  STATUS=$(git status --short -- "$SUBDIR")
  if [ -n "$STATUS" ]; then
    log "ATTENTION: modifications non commitees dans $SUBDIR :"
    echo "$STATUS" | tee -a "$LOG"
  fi
else
  log "ATTENTION: $REPO n'est pas un depot git - verification diff/status impossible"
fi

# 4. Restart + health check
log "Redemarrage de $SERVICE..."
sudo systemctl restart "$SERVICE"
sleep 4

CODE=$(health_check "$PORT")
MODE="anonyme"; [ -n "$AUTH" ] && MODE="authentifie"
log "Health check http://127.0.0.1:$PORT/ ($MODE) -> HTTP $CODE"

if [ "$CODE" = "000" ] || [[ "$CODE" =~ ^5[0-9][0-9]$ ]]; then
  log "ECHEC health check (HTTP $CODE) - rollback automatique de $SUBDIR vers HEAD"
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git checkout HEAD -- "$SUBDIR" 2>>"$LOG"
  fi
  sudo systemctl restart "$SERVICE"
  sleep 4
  CODE2=$(health_check "$PORT")
  log "Health check apres rollback -> HTTP $CODE2"
  send_alert "[VPS] $SERVICE en echec - rollback automatique effectue" "Le redemarrage de $SERVICE a echoue (health check HTTP $CODE sur http://127.0.0.1:$PORT/). Rollback vers la derniere version commitee (git checkout HEAD -- $SUBDIR) puis restart automatique effectue. Nouveau health check : HTTP $CODE2. Verifier : sudo journalctl -u $SERVICE -n 100"
  exit 1
fi

log "OK: $SERVICE redemarre et operationnel (HTTP $CODE)"
exit 0
