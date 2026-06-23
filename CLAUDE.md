# Infrastructure ? Chlo? Ludmann Automations

## VPS

- **IP** : 83.228.240.50
- **User** : ubuntu
- **Connexion** : `ssh -i "C:\Users\sophi\cle-automations" ubuntu@83.228.240.50`
- **R?pertoire principal** : `/home/ubuntu/automations/`
- **venv** : `/home/ubuntu/automations/venv/`
- **Fichier de config** : `/home/ubuntu/automations/.env` (toutes les cl?s et mots de passe)

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
- **Remote** : configur? avec token HTTPS dans l'URL (dans le remote git local)
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

L'app `export_excel/app.py` (port 5003, route `/export-eleves`) n'a pas de service systemd ? ? v?rifier si elle est lanc?e manuellement.

---

## Automatisations (crons)

7 t?ches planifi?es dans `crontab -l` pour l'user `ubuntu`.

### 1. `imap_to_notion_chloe.py`
- **Cron** : tous les jours ? 19h30
- **R?le** : Lit les bo?tes IMAP de Chlo? (OVH + Infomaniak), classe les emails via Claude (Haiku), cr?e des entr?es dans la base Notion ?v?nements
- **Comptes lus** : `IMAP_EMAIL` (contact@chloeludmann.fr) + `IMAP_EMAIL_WHISPER` (contact@whisper-in-the-rennes.fr)
- **Log** : `logs/imap_to_notion_chloe.log`

### 2. `daily_summary.py`
- **Cron** : tous les jours ? 20h
- **R?le** : R?cup?re les ?v?nements Notion des 24h pass?es, g?n?re un r?sum? HTML via Claude, l'envoie par email (SMTP Gmail)
- **Destinataires** : contact@chloeludmann.fr + bour.chloe0@gmail.com
- **Log** : `logs/daily_summary.log`

### 3. `docage_to_notion.py`
- **Cron** : lundi, mercredi, vendredi ? 8h
- **R?le** : Synchronise les transactions de signature Docage vers Notion (base ?v?nements). Option `--resend` pour relancer les contrats bloqu?s ? "Relanc?"
- **Log** : `logs/docage_to_notion.log`

### 4. `factures/factures.py`
- **Cron** : lundi ? 8h
- **R?le** : Scan des factures depuis Google Drive, traitement et mise ? jour Notion
- **Log** : `logs/factures.log`

### 5. `liste_attente/monitor.py`
- **Cron** : tous les jours ? 7h
- **R?le** : V?rifie que le webhook Calendly est actif et que le SMTP fonctionne. Envoie une alerte ? contact@sophieboutemy.com en cas d'?chec
- **Log** : `logs/monitor.log`

### 6. `weekly_backup.py`
- **Cron** : dimanche ? 20h
- **R?le** : Export JSON de la base Notion ?l?ves vers `backups/backup_eleves_YYYY-MM-DD.json`. Nettoyage des backups de plus de 30 jours
- **Log** : `logs/weekly_backup.log`

### 7. `backup_complet.sh`
- **Cron** : dimanche ? 21h
- **R?le** : Backup complet du VPS (script shell)
- **Log** : `logs/backup_complet.log`

---

## Bases Notion utilis?es

| Base | ID | Usage |
|---|---|---|
| ?l?ves / ?v?nements | `35eafa74cfc980d092d0e80644bd6be7` | Base principale ? emails entrants, r?sum?s, backups, Docage |
| Factures | `327afa74cfc980328301eec9bb7996e5` | Suivi factures (dashboard + scan) |
| Import BTP | `318afa74cfc981148528e6791c72f1cc` | Import ponctuel (`import_notion_btp.py`) |
| `NOTION_DATABASE_ID` | (voir .env) | Script legacy `gmail_to_notion.py` |

---

## Variables d'environnement (.env)

Toutes les valeurs r?elles sont dans `/home/ubuntu/automations/.env`. Ne jamais les committer.

| Variable | Usage |
|---|---|
| `ANTHROPIC_API_KEY` | API Claude ? classification emails et g?n?ration de r?sum?s |
| `NOTION_API_KEY` | Acc?s API Notion ? toutes les automatisations |
| `NOTION_DATABASE_ID` | ID base Notion (script legacy `gmail_to_notion.py`) |
| `IMAP_EMAIL` | Adresse bo?te OVH de Chlo? (contact@chloeludmann.fr) |
| `IMAP_PASSWORD` | Mot de passe IMAP OVH |
| `IMAP_EMAIL_WHISPER` | Adresse bo?te Infomaniak Whisper |
| `IMAP_PASSWORD_WHISPER` | Mot de passe IMAP Infomaniak |
| `GMAIL_IMAP_EMAIL` | Email Gmail (lecture IMAP) |
| `GMAIL_AUTOMATION_PASSWORD` | App password Gmail pour envoi SMTP (boutemy.automatisation@gmail.com) |
| `SMTP_PASS` | Mot de passe SMTP (alias ou usage futur) |
| `DOCAGE_EMAIL` | Email du compte Docage |
| `DOCAGE_API_KEY` | Cl? API Docage (signatures ?lectroniques) |
| `CALENDLY_TOKEN` | Token API Calendly |
| `CALENDLY_URL` | URL du profil Calendly de Chlo? |
| `DRIVE_FOLDER_ID` | ID du dossier Google Drive (factures) |
| `DRIVE_FACTURES_URL` | URL du dossier Drive factures |
| `DASHBOARD_USER` | Login admin du dashboard Chlo? |
| `DASHBOARD_PASSWORD` | Mot de passe admin du dashboard Chlo? |
| `DASHBOARD_SECRET_KEY` | Cl? secr?te Flask session (chloe-dashboard) |
| `DASHBOARD_USER_EMAIL` | Email de l'admin du dashboard |
| `SOPHIE_DASHBOARD_USER` | Login admin Mon Espace Pro |
| `SOPHIE_DASHBOARD_PASSWORD` | Mot de passe admin Mon Espace Pro |
| `SOPHIE_DASHBOARD_EMAIL` | Email admin Mon Espace Pro |
| `SOPHIE_DASHBOARD_SECRET_KEY` | Cl? secr?te Flask session (sophie-dashboard) |
| `VPS_URL` | URL publique du VPS |

---

## Calendly ? Planning de Chlo?

**Schedule actif** : "Sept 2026 > Juillet 2027" (default=True), timezone Europe/Berlin.

### R?gles de base (wday)

Lundi ? vendredi ouverts **09h00?20h00** sans exception. Samedi et dimanche ferm?s.  
Aucun jour de semaine n'est ferm? par d?faut ? le planning de base couvre les 5 jours.

### Gestion des disponibilit?s r?elles

Chlo? ne se base pas sur la r?gle wday pour ses journ?es r?elles : elle pose des exceptions `type=date` individuelles sur chaque jour travaill? (horaires pr?cis, souvent 14h?18h30 ou 09h?13h30). La r?gle wday 09h?20h sert de filet de s?curit?, mais en pratique presque chaque jour a sa propre exception.

**Ce comportement est intentionnel ? c'est le vrai planning de Chlo?, pas un bug ? corriger.** Ne pas "normaliser" les exceptions `type=date` vers la r?gle wday.

### Vacances / fermetures connues (v?rifi?es via API)

Les vacances sont des exceptions `type=date` avec `intervals=[]` qui ?crasent la r?gle wday.

| P?riode | Dates |
|---|---|
| ?t? 2026 | 4 ao?t ? 28 ao?t 2026 (1er ao?t encore ouvert, 31 ao?t r?ouverture) |
| Toussaint 2026 | 26, 27, 28, 29, 30 oct 2026 ? 5 exceptions `type=date intervals=[]` individuelles, toute la semaine ferm?e. |
| No?l 2026 | 20 d?c ? 31 d?c 2026 |
| Carnaval/hiver 2027 | 1er mars ? 5 mars 2027 |
| Ascension 2027 | 9 mai ? 22 mai 2027 |
| ?t? 2027 | ? partir du 3 ao?t 2027 |

### Source de v?rit? pour les cr?neaux

`GET /event_type_available_times` est la seule source fiable pour savoir si un cr?neau est r?servable. Le schedule donne le contexte (vacances, horaires), mais l'API retourne l'?tat r?el apr?s fusion des r?gles, exceptions, et r?servations existantes.

### Types de rules disponibles dans l'API

L'endpoint `GET /user_availability_schedules` ne retourne que deux types de rules :
- `wday` ? r?gle r?currente par jour de semaine (7 entr?es : lun?dim)
- `date` ? exception sur une date pr?cise (329 entr?es sur le schedule actuel)

Il n'existe pas de type `range` ou `date_range` dans cet endpoint. Les fermetures multi-jours (vacances) sont toujours des exceptions `type=date` individuelles, une par jour.

### Plage de r?servation des event types cours r?guliers

Les 4 event types de cours r?guliers (#15-18) sont configur?s sur **"Ind?finiment"** (pas de date limite fixe). Ne pas remettre de limite de date ? c'est voulu pour que les ?l?ves puissent r?server sur toute la saison disponible.

---

## `recurrence_calendly` ? Logique et ?tat (mis ? jour 2026-06-23)

Dossier : `~/automations/recurrence_calendly/`

### Logique `check_and_book`

- `check_and_book()` appelle **toujours** `GET /event_type_available_times` en premier.
- Si l'API retourne une liste vide ? statut `unavailable` directement. **Il n'y a plus de logique "pending automatique pour les dates lointaines"** (supprim?e).
- Exception : une race condition est possible au moment exact du booking (cr?neau pris entre le check et la r?servation) ? dans ce cas seulement, le pending peut appara?tre transitoirement.
- `WINDOW_DAYS=365` dans `.env` ? conserv? mais ne sert plus ? classifier une r?ponse vide.

### Fr?quence paire/impaire

- Le champ Tally **"Type de semaines"** (semaines paires / impaires / toutes) est lu ? l'entr?e du formulaire.
- Mappage r?alis? dans `resolve_field()` : la valeur Tally est convertie en filtre de semaine avant d'interroger les cr?neaux.
- Ne pas modifier cette logique sans v?rifier la concordance avec les intitul?s exacts des options Tally.

### SMTP ? situation actuelle (? r?soudre)

**Solution temporaire en production** : Gmail SMTP via `boutemy.automatisation@gmail.com` (app password `GMAIL_AUTOMATION_PASSWORD`). Le champ `From` affich? est "Chlo? Ludmann" ? fonctionne en d?livrabilit?.

**Pistes test?es et abandonn?es** :
- **OVH** : le relay SMTP accepte la connexion mais les emails ne sont jamais d?livr?s (pas d'erreur, pas d'accus? ? silencieux). Abandonn?.
- **Brevo** : compte existant mais le SMTP transactionnel n'a jamais ?t? activ? (n?cessite un ticket support Brevo). Mis en attente.

**? faire** : ouvrir un ticket Brevo pour activer le SMTP transactionnel, puis migrer depuis Gmail. Ne pas retenter OVH.

### Templates email ? charte graphique

`build_email_client()` et `build_email_chloe()` utilisent **strictement** la palette suivante ? ne pas inventer d'autres teintes :

| R?le | Couleur | Hex |
|---|---|---|
| Vert principal | `#419958` | Boutons, accents |
| Rouge / alerte | `#EA4F26` | Annulations, urgences |
| Rose | `#FFB7DD` | Accents doux |
| Beige fond | `#F8EFE2` | Fond des emails |
| Noir texte | `#23242C` | Corps de texte |

`color-scheme: light` est forc? dans les styles inline pour ?viter que les clients mail (Gmail app, Apple Mail dark mode) n'inversent les couleurs.

---

## Logs

Tous dans `~/automations/logs/`. Pas de logrotate configur? ? rotation manuelle.

## Scripts utilitaires (non planifi?s)

- `_check_props.py`, `_diag_*.py` ? diagnostics ponctuels
- `_restore_fiche.py` ? restauration d'une fiche Notion depuis backup
- `auth_gmail.py`, `reauth_drive.py`, `refresh_gmail_token.py` ? renouvellement tokens OAuth Google
- `check_notion.py`, `test_*.py` ? tests et v?rifications manuelles
- `scripts/gmail_notion_classification.py` ? version exp?rimentale de classification Gmail
