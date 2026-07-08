# Cron — calendly_sync_eleves.py

Synchronise les invités Calendly (compte Chloé Ludmann) vers la base Notion
"Élèves" : crée une fiche pour chaque email absent de la base, avec la date
de son premier événement réservé (voir docstring de `calendly_sync_eleves.py`).

## Tâche cron

- **Fréquence** : tous les lundis à 6h00 (heure creuse)
- **Portée** : tout l'historique Calendly à chaque run (pas de filtre de
  date) — le script ne crée que les emails absents de la base, donc rejouer
  tout l'historique est idempotent et permet de rattraper d'éventuels trous
  plus anciens détectés plus tard. Reste rapide (quelques minutes) grâce à
  la parallélisation des appels `/invitees` (10 workers, cooldown partagé
  sur 429).
- **Mode** : réel (`--all-history`, sans `--dry-run`)
- **Log** : un fichier daté par run — `logs/calendly_sync_YYYY-MM-DD.log`
  (progression, emails créés, ou trace d'erreur si le run échoue)

## Commande crontab (utilisateur ubuntu, `crontab -e`)

```
0 6 * * 1 cd /home/ubuntu/automations && LOGFILE=/home/ubuntu/automations/logs/calendly_sync_$(date +\%Y-\%m-\%d).log && venv/bin/python calendly_sync_eleves.py --all-history >> "$LOGFILE" 2>&1 || echo "$(date "+\%Y-\%m-\%d \%H:\%M:\%S") ERREUR : calendly_sync_eleves.py a echoue - voir traceback ci-dessus" >> "$LOGFILE"
```

## Options du script

```
python calendly_sync_eleves.py                         # sync réelle, filtrée depuis MIN_START_TIME
python calendly_sync_eleves.py --dry-run                # simulation, aucune écriture Notion
python calendly_sync_eleves.py --dry-run --all-history  # simulation, tout l'historique Calendly
python calendly_sync_eleves.py --all-history             # sync réelle, tout l'historique (mode cron)
```
