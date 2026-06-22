# Infrastructure — Chloé Ludmann Automations

## VPS

- **IP** : 83.228.240.50
- **User** : ubuntu
- **Connexion** : `ssh -i "C:\Users\sophi\cle-automations" ubuntu@83.228.240.50`
- **Répertoire principal** : `/home/ubuntu/automations/`
- **venv** : `/home/ubuntu/automations/venv/`
- **Fichier de config** : `/home/ubuntu/automations/.env` (toutes les clés et mots de passe)

## Domaines & Nginx

| Domaine | Usage |
|---|---|
| `automations.chloeludmann.fr` | Reverse proxy principal (HTTPS, Let's Encrypt) |
| `mon-adjoint-ia.fr` | Site statique `/var/www/mon-adjoint-ia` |
| `pro.mon-adjoint-ia.fr` | Dashboard Sophie (port 5006) |

Nginx config : `/etc/nginx/sites-enabled/`

## GitHub

- **Repo** : `https://github.com/lapetitefabriquedigitale/ChloeLudmann.git`
- **Branche** : `main`
- **Remote** : configuré avec token HTTPS dans l'URL (dans le remote git local)
- **Backup auto** : commit hebdomadaire via cron (`weekly_backup.py`)

---

## Services systemd (toujours actifs)

| Service | Fichier | Port | URL publique |
|---|---|---|---|
| `chloe-dashboard.service` | `chloe-dashboard/app.py` | 5005 | `/dashboard/` |
| `factures-app.service` | `factures/app.py` | 5004 | `/scan-factures` |
| `liste-attente.service` | `liste_attente/app.py` | 5002 | `/` (racine domaine) |
| `sophie-dashboard.service` | `/home/ubuntu/sophie-dashboard/app.py` | 5006 | `pro.mon-adjoint-ia.fr` |

Commandes utiles :
```bash
sudo systemctl status <service>
sudo systemctl restart <service>
sudo journalctl -u <service> -n 50
```

L'app `export_excel/app.py` (port 5003, route `/export-eleves`) n'a pas de service systemd — à vérifier si elle est lancée manuellement.

---

## Automatisations (crons)

7 tâches planifiées dans `crontab -l` pour l'user `ubuntu`.

### 1. `imap_to_notion_chloe.py`
- **Cron** : tous les jours à 19h30
- **Rôle** : Lit les boîtes IMAP de Chloé (OVH + Infomaniak), classe les emails via Claude (Haiku), crée des entrées dans la base Notion Événements
- **Comptes lus** : `IMAP_EMAIL` (contact@chloeludmann.fr) + `IMAP_EMAIL_WHISPER` (contact@whisper-in-the-rennes.fr)
- **Log** : `logs/imap_to_notion_chloe.log`

### 2. `daily_summary.py`
- **Cron** : tous les jours à 20h
- **Rôle** : Récupère les événements Notion des 24h passées, génère un résumé HTML via Claude, l'envoie par email (SMTP Gmail)
- **Destinataires** : contact@chloeludmann.fr + bour.chloe0@gmail.com
- **Log** : `logs/daily_summary.log`

### 3. `docage_to_notion.py`
- **Cron** : lundi, mercredi, vendredi à 8h
- **Rôle** : Synchronise les transactions de signature Docage vers Notion (base Événements). Option `--resend` pour relancer les contrats bloqués à "Relancé"
- **Log** : `logs/docage_to_notion.log`

### 4. `factures/factures.py`
- **Cron** : lundi à 8h
- **Rôle** : Scan des factures depuis Google Drive, traitement et mise à jour Notion
- **Log** : `logs/factures.log`

### 5. `liste_attente/monitor.py`
- **Cron** : tous les jours à 7h
- **Rôle** : Vérifie que le webhook Calendly est actif et que le SMTP fonctionne. Envoie une alerte à contact@sophieboutemy.com en cas d'échec
- **Log** : `logs/monitor.log`

### 6. `weekly_backup.py`
- **Cron** : dimanche à 20h
- **Rôle** : Export JSON de la base Notion Élèves vers `backups/backup_eleves_YYYY-MM-DD.json`. Nettoyage des backups de plus de 30 jours
- **Log** : `logs/weekly_backup.log`

### 7. `backup_complet.sh`
- **Cron** : dimanche à 21h
- **Rôle** : Backup complet du VPS (script shell)
- **Log** : `logs/backup_complet.log`

---

## Bases Notion utilisées

| Base | ID | Usage |
|---|---|---|
| Élèves / Événements | `35eafa74cfc980d092d0e80644bd6be7` | Base principale — emails entrants, résumés, backups, Docage |
| Factures | `327afa74cfc980328301eec9bb7996e5` | Suivi factures (dashboard + scan) |
| Import BTP | `318afa74cfc981148528e6791c72f1cc` | Import ponctuel (`import_notion_btp.py`) |
| `NOTION_DATABASE_ID` | (voir .env) | Script legacy `gmail_to_notion.py` |

---

## Variables d'environnement (.env)

Toutes les valeurs réelles sont dans `/home/ubuntu/automations/.env`. Ne jamais les committer.

| Variable | Usage |
|---|---|
| `ANTHROPIC_API_KEY` | API Claude — classification emails et génération de résumés |
| `NOTION_API_KEY` | Accès API Notion — toutes les automatisations |
| `NOTION_DATABASE_ID` | ID base Notion (script legacy `gmail_to_notion.py`) |
| `IMAP_EMAIL` | Adresse boîte OVH de Chloé (contact@chloeludmann.fr) |
| `IMAP_PASSWORD` | Mot de passe IMAP OVH |
| `IMAP_EMAIL_WHISPER` | Adresse boîte Infomaniak Whisper |
| `IMAP_PASSWORD_WHISPER` | Mot de passe IMAP Infomaniak |
| `GMAIL_IMAP_EMAIL` | Email Gmail (lecture IMAP) |
| `GMAIL_AUTOMATION_PASSWORD` | App password Gmail pour envoi SMTP (boutemy.automatisation@gmail.com) |
| `SMTP_PASS` | Mot de passe SMTP (alias ou usage futur) |
| `DOCAGE_EMAIL` | Email du compte Docage |
| `DOCAGE_API_KEY` | Clé API Docage (signatures électroniques) |
| `CALENDLY_TOKEN` | Token API Calendly |
| `CALENDLY_URL` | URL du profil Calendly de Chloé |
| `DRIVE_FOLDER_ID` | ID du dossier Google Drive (factures) |
| `DRIVE_FACTURES_URL` | URL du dossier Drive factures |
| `DASHBOARD_USER` | Login admin du dashboard Chloé |
| `DASHBOARD_PASSWORD` | Mot de passe admin du dashboard Chloé |
| `DASHBOARD_SECRET_KEY` | Clé secrète Flask session (chloe-dashboard) |
| `DASHBOARD_USER_EMAIL` | Email de l'admin du dashboard |
| `SOPHIE_DASHBOARD_USER` | Login admin Mon Espace Pro |
| `SOPHIE_DASHBOARD_PASSWORD` | Mot de passe admin Mon Espace Pro |
| `SOPHIE_DASHBOARD_EMAIL` | Email admin Mon Espace Pro |
| `SOPHIE_DASHBOARD_SECRET_KEY` | Clé secrète Flask session (sophie-dashboard) |
| `VPS_URL` | URL publique du VPS |

---

## Calendly — Planning de Chloé

**Schedule actif** : "Sept 2026 > Juillet 2027" (default=True), timezone Europe/Berlin.

### Règles de base (wday)

Lundi à vendredi ouverts **09h00–20h00** sans exception. Samedi et dimanche fermés.  
Aucun jour de semaine n'est fermé par défaut — le planning de base couvre les 5 jours.

### Gestion des disponibilités réelles

Chloé ne se base pas sur la règle wday pour ses journées réelles : elle pose des exceptions `type=date` individuelles sur chaque jour travaillé (horaires précis, souvent 14h–18h30 ou 09h–13h30). La règle wday 09h–20h sert de filet de sécurité, mais en pratique presque chaque jour a sa propre exception.

### Vacances / fermetures connues (vérifiées via API)

Les vacances sont des exceptions `type=date` avec `intervals=[]` qui écrasent la règle wday.

| Période | Dates |
|---|---|
| Été 2026 | 4 août → 28 août 2026 (1er août encore ouvert, 31 août réouverture) |
| Toussaint 2026 | 26, 27, 28, 29, 30 oct 2026 — 5 exceptions `type=date intervals=[]` individuelles, toute la semaine fermée. |
| Noël 2026 | 20 déc → 31 déc 2026 |
| Carnaval/hiver 2027 | 1er mars → 5 mars 2027 |
| Ascension 2027 | 9 mai → 22 mai 2027 |
| Été 2027 | à partir du 3 août 2027 |

### Source de vérité pour les créneaux

`GET /event_type_available_times` est la seule source fiable pour savoir si un créneau est réservable. Le schedule donne le contexte (vacances, horaires), mais l'API retourne l'état réel après fusion des règles, exceptions, et réservations existantes.

### Types de rules disponibles dans l'API

L'endpoint `GET /user_availability_schedules` ne retourne que deux types de rules :
- `wday` — règle récurrente par jour de semaine (7 entrées : lun–dim)
- `date` — exception sur une date précise (329 entrées sur le schedule actuel)

Il n'existe pas de type `range` ou `date_range` dans cet endpoint. Les fermetures multi-jours (vacances) sont toujours des exceptions `type=date` individuelles, une par jour.

### `recurrence_calendly` — logique de fenêtre

`WINDOW_DAYS=365` dans `.env`. `check_and_book()` appelle toujours `available_times` en premier ; `WINDOW_DAYS` ne sert qu'à classifier une réponse vide (lointain → pending, proche → unavailable).

---

## Logs

Tous dans `~/automations/logs/`. Pas de logrotate configuré — rotation manuelle.

## Scripts utilitaires (non planifiés)

- `_check_props.py`, `_diag_*.py` — diagnostics ponctuels
- `_restore_fiche.py` — restauration d'une fiche Notion depuis backup
- `auth_gmail.py`, `reauth_drive.py`, `refresh_gmail_token.py` — renouvellement tokens OAuth Google
- `check_notion.py`, `test_*.py` — tests et vérifications manuelles
- `scripts/gmail_notion_classification.py` — version expérimentale de classification Gmail
