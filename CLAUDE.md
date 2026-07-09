# Règles permanentes — efficacité des commandes

Avant d'exécuter une commande shell/SSH/Python :
1. **Regrouper** : combiner plusieurs actions en un seul aller-retour si possible.
2. **Patch ciblé** : utiliser `str_replace` / `Edit` sur la section concernée plutôt que de réécrire un fichier entier.
3. **Justifier les tests exploratoires** : si la commande sert à "voir si ça marche", le dire en une ligne avant de la lancer.
4. **Erreur d'échappement shell** : ne pas réessayer plusieurs variantes — écrire un script `.py` temporaire sur le serveur et l'exécuter une fois.
5. **Sync avant modification** : avant toute session de travail sur un projet déployé sur le VPS (`automations/`, `sophie-dashboard/`, `sites-statiques/*`), faire `git fetch && git status --branch` pour vérifier que la copie locale/serveur est à jour avec `origin`. En cas de divergence (commits en avance/retard, ou modifications non commitées inattendues), s'arrêter et le signaler à l'utilisateur avant de continuer — ne jamais modifier un fichier dont l'état de synchronisation est incertain. (Root cause du 2026-07-08 : un agent a réécrit `chloe-dashboard/app.py` en entier depuis une copie locale obsolète sans vérifier l'état git au préalable, écrasant ~900 lignes de fonctionnalités récentes.)
6. **Restart de service = `deploy_check.sh`, jamais `systemctl restart` direct** : pour redémarrer un service Flask sur le VPS, toujours utiliser `~/automations/scripts/deploy_check.sh <service_name>` (jamais `sudo systemctl restart <service>` directement, sauf urgence explicitement assumée). Le script vérifie la syntaxe Python du fichier principal, détecte une perte de code anormale (>20% de lignes en moins vs le dernier commit git), signale les fichiers non commités, fait un health check HTTP post-restart, et rollback automatiquement (`git checkout HEAD -- <dossier du service>`) + alerte email en cas d'échec. Services connus : `chloe-dashboard`, `factures-app`, `liste-attente`, `recurrence-calendly`, `export-eleves`, `sophie-dashboard`.

Objectif : minimiser le nombre de commandes et le volume de tokens par session, sans sacrifier la correction.

---

# Infrastructure VPS — Automations Sophie Boutemy

VPS OVH partagé entre deux projets : les automatisations de **Chloé Ludmann** et le **dashboard personnel Sophie**. Tout tourne sur le même serveur, avec des services systemd distincts par module.

- **IP** : 83.228.240.50
- **User** : ubuntu
- **Connexion** : `ssh -i "C:\Users\sophi\cle-automations" ubuntu@83.228.240.50`
- **Répertoire principal** : `/home/ubuntu/automations/`
- **Fichier .env** : `/home/ubuntu/automations/.env` (toutes les clés et mots de passe, partagé entre les deux projets)

---

## Domaines & Nginx

| Domaine | Usage |
|---|---|
| `automations.chloeludmann.fr` | Reverse proxy principal — services de Chloé (HTTPS, Let's Encrypt) |
| `automations.chloeludmann.fr/dashboard/` | Dashboard Chloé (port 5005) |
| `mon-adjoint-ia.fr` | Site statique `/var/www/mon-adjoint-ia` |
| `pro.mon-adjoint-ia.fr` | Dashboard Sophie (port 5006) |

Nginx configs : `/etc/nginx/sites-enabled/`

---

## Services systemd

| Service | Fichier | Port | URL publique |
|---|---|---|---|
| `chloe-dashboard.service` | `automations/chloe-dashboard/app.py` | 5005 | `automations.chloeludmann.fr/dashboard/` |
| `factures-app.service` | `automations/factures/app.py` | 5004 | `/scan-factures` |
| `liste-attente.service` | `automations/liste_attente/app.py` | 5002 | `/` (racine domaine) |
| `recurrence-calendly.service` | `automations/recurrence_calendly/app.py` | 5007 | `/recurrence-webhook` |
| `export-eleves.service` | `automations/export_excel/app.py` | 5003 | `/export-eleves` |
| `sophie-dashboard.service` | `sophie-dashboard/app.py` | 5006 | `pro.mon-adjoint-ia.fr` |

Commandes utiles :
```bash
sudo systemctl status <service>
~/automations/scripts/deploy_check.sh <service>   # restart avec garde-fous — voir règle 6 ci-dessus, ne pas utiliser systemctl restart directement
sudo journalctl -u <service> -n 50
```

---

## Crons (user ubuntu)

| Script | Fréquence | Rôle |
|---|---|---|
| `imap_to_notion_chloe.py` | Tous les jours à 19h30 | Lecture IMAP, classification Claude, écriture Notion |
| `daily_summary.py` | Tous les jours à 20h | Résumé des 24h par email |
| `docage_to_notion.py` | Lun, mer, ven à 8h | Sync signatures Docage → Notion |
| `factures/factures.py` | Lundis à 8h | Récupère factures IMAP → Drive |
| `liste_attente/monitor.py` | Tous les jours à 7h | Vérifie que le webhook Calendly est actif |
| `recurrence_calendly/retry.py` | Tous les jours à 7h | Relance les créneaux Calendly en attente |
| `weekly_backup.py` | Dimanches à 20h | Export JSON base Notion élèves |
| `backup_complet.sh` | Dimanches à 21h | Backup complet VPS |
| `purge_rgpd.py` | 1er du mois à 3h | Purge RGPD automatique (non documenté dans chloe-dashboard) |

---

## Backup complet (`backup_complet.sh`)

**Script** : `/home/ubuntu/backups/backup_complet.sh` (PAS dans `automations/`)
**Log** : `/home/ubuntu/automations/logs/backup_complet.log`

Exécution en 5 étapes chaque dimanche à 21h :

1. **Archive code** → `~/backups/code-DATE.tar.gz`
   - Contenu : `~/automations/` + `~/sophie-dashboard/`
   - Exclusions : `venv/`, `__pycache__/`, `.git/`, `backups/`, `logs/`, `waitlist.json`, `processed_emails.json`

2. **Archive secrets chiffrée** → `~/backups/secrets-DATE.tar.gz.gpg`
   - Contenu : `.env`, `credentials.json`, `token.json`, `factures/service_account.json`
   - Chiffrement : GPG AES256, passphrase dans `~/.gpg_backup_passphrase`

3. **Push git** : `git add -A && git commit -m "auto: backup DATE" && git push` sur les deux repos (automations + sophie-dashboard)

4. **Upload Google Drive** : `rclone copy` vers remote `gdrive-perso` → `Backups VPS/code/` et `Backups VPS/secrets/`

5. **Nettoyage local** : archives (code + secrets + `sophie-dashboard-*.tar.gz`) de plus de 30 jours supprimées. Drive conservé indéfiniment.

---

## GitHub

**Compte actif : `SophieBoutemy`** (migration terminée le 2026-07-09, suite à un ancien token `lapetitefabriquedigitale` compromis — exposé en clair dans une sortie de commande — et révoqué).

- **Repo Chloé** : `https://github.com/SophieBoutemy/ChloeLudmann.git` — dans `~/automations`, branche `main`.
- **Repo Sophie** : `https://github.com/SophieBoutemy/MonEspacePro.git` — dans `~/sophie-dashboard`, branche `main`.
- **Repo sophieboutemy.fr** : `https://github.com/SophieBoutemy/sophieboutemy.git` — dans `~/sites-statiques/sophieboutemy`, branche `master`.
- **Authentification** : `credential.helper store` global, token stocké dans `~/.git-credentials` (permissions `600`). **Jamais** de token en clair dans une URL de remote — `git remote -v` doit toujours rester propre sur les 3 repos.
- **Backup auto** : commit hebdomadaire via cron (dimanche 21h, `backup_complet.sh`), cible `~/automations` (et non plus `~/chloe-automations`, copie de migration abandonnée le 2026-07-09 et renommée `~/chloe-automations.bak-20260709`).
- **`SophieBoutemy/monadjointia`** et **`SophieBoutemy/lpfd`** sont des repos distincts (sites statiques `mon-adjoint-ia.fr` et `lapetitefabriquedigitale.fr`), sans rapport avec `sophie-dashboard` — ne pas confondre.

---

## Bases Notion utilisées

| Base | ID | Usage |
|---|---|---|
| Élèves / Événements | `35eafa74cfc980d092d0e80644bd6be7` | Base principale — emails, résumés, backups, Docage |
| Factures | `327afa74cfc980328301eec9bb7996e5` | Adjoint Factures |
| Import BTP | `318afa74cfc981148528e6791c72f1cc` | Import ponctuel (`import_notion_btp.py`) |

---

## Variables d'environnement (.env)

Fichier : `/home/ubuntu/automations/.env`. Ne jamais committer les valeurs.

| Variable | Usage |
|---|---|
| `ANTHROPIC_API_KEY` | API Claude — classification emails et résumés |
| `NOTION_API_KEY` | Accès API Notion |
| `NOTION_DATABASE_ID` | ID base Notion (script legacy `gmail_to_notion.py`) |
| `IMAP_EMAIL` | contact@chloeludmann.fr (OVH) |
| `IMAP_PASSWORD` | Mot de passe IMAP OVH |
| `IMAP_EMAIL_WHISPER` | contact@whisper-in-the-rennes.fr (Infomaniak) |
| `IMAP_PASSWORD_WHISPER` | Mot de passe IMAP Infomaniak |
| `GMAIL_AUTOMATION_PASSWORD` | App password Gmail SMTP (boutemy.automatisation@gmail.com) |
| `SMTP_PASS` | Mot de passe SMTP (alias ou usage futur) |
| `DOCAGE_EMAIL` | Email du compte Docage |
| `DOCAGE_API_KEY` | Clé API Docage (signatures électroniques) |
| `CALENDLY_TOKEN` | Token API Calendly |
| `CALENDLY_URL` | URL du profil Calendly de Chloé |
| `DRIVE_FOLDER_ID` | ID du dossier Google Drive (factures) |
| `DRIVE_FACTURES_URL` | URL du dossier Drive factures |
| `DASHBOARD_USER` | Login admin dashboard Chloé |
| `DASHBOARD_PASSWORD` | Mot de passe admin dashboard Chloé |
| `DASHBOARD_SECRET_KEY` | Clé secrète Flask (chloe-dashboard) |
| `DASHBOARD_USER_EMAIL` | Email admin dashboard Chloé |
| `SOPHIE_DASHBOARD_USER` | Login admin Mon Adjoint IA |
| `SOPHIE_DASHBOARD_PASSWORD` | Mot de passe admin Mon Adjoint IA |
| `SOPHIE_DASHBOARD_EMAIL` | Email admin Mon Adjoint IA |
| `SOPHIE_DASHBOARD_SECRET_KEY` | Clé secrète Flask (sophie-dashboard) |
| `VPS_URL` | URL publique du VPS |

---

---

# Automatisations — Projet Chloé Ludmann

Dashboard : `https://automations.chloeludmann.fr/dashboard/`
Répertoire : `/home/ubuntu/automations/`

---

## Dashboard Chloé — Interface Flask

**Service** : `chloe-dashboard.service` — port 5005
**Fichier principal** : `automations/chloe-dashboard/app.py`
**Middleware** : `ProxyFix(x_proto=1, x_prefix=1)` — nécessaire car Nginx sert sous le préfixe `/dashboard/`

### Authentification

- Login : comparaison directe `DASHBOARD_USER` / `DASHBOARD_PASSWORD` (variables .env), session Flask
- **Reset mot de passe** : token signé `itsdangerous` (sel `password-reset`, durée 1h) → email envoyé à `DASHBOARD_USER_EMAIL` via OVH SMTP SSL port 465 (`IMAP_EMAIL` / `IMAP_PASSWORD`) → mise à jour immédiate en mémoire + réécriture dans `.env` via `set_key`
- Routes : `GET/POST /login`, `GET /logout`, `GET/POST /forgot-password`, `GET/POST /reset-password/<token>`

### Données du tableau de bord — `automations.json`

Source de vérité pour les statuts affichés sur la page d'accueil. Chaque entrée :

| Champ | Usage |
|---|---|
| `agent` | Clé de regroupement (ex. `"Suivi Élèves"`, `"Factures"`) — correspond à `agent_key` dans `_AGENT_CARDS` |
| `trigger` | `"cron"` → vérifie le log ; `"systemd"` → vérifie le service |
| `log` + `stale_after_hours` | Chemin du log et seuil de fraîcheur (dot orange si dépassé) |
| `service` | Nom du service systemd à vérifier |
| `agent: "_hidden"` | Entrée interne non affichée dans le dashboard |

### Structure `_AGENT_CARDS`

Liste ordonnée des cards affichées sur la page d'accueil. Chaque card :
- `title` : nom affiché (ex. `"Adjoint Client"`)
- `agent_key` : filtre dans `automations.json` pour récupérer les scénarios et leurs statuts (vide `""` = pas de statuts temps réel)
- `btn_label` / `btn_endpoint` : bouton d'accès au module (`url_for(btn_endpoint)`)
- `description` : texte affiché si `agent_key` est vide

Cards actuelles (dans l'ordre) : Adjoint Client, Adjoint Factures, Adjoint Attente, Adjoint Social, Adjoint Planning, Adjoint Prospection.

### Routes principales

| Méthode | Route | Auth | Description |
|---|---|---|---|
| GET/POST | `/login` | non | Login |
| GET | `/logout` | non | Déconnexion |
| GET/POST | `/forgot-password` | non | Demande reset MDP |
| GET/POST | `/reset-password/<token>` | non | Réinitialisation MDP (token 1h) |
| GET | `/` | oui | Tableau de bord principal |
| GET | `/eleves` | oui | Liste des élèves (Notion) |
| GET | `/factures` | oui | Liste des factures |
| GET | `/liste-attente` | oui | Liste d'attente |
| GET | `/brief-to-post` | oui | Adjoint Social (brief → contenu IA) |
| GET/POST | `/rgpd` | oui | Purge RGPD (voir ci-dessous) |
| GET | `/prospection` | oui | Module Adjoint Prospection |

### Route RGPD — droit à l'effacement (`/rgpd`)

**Accès** : `@login_required` — réservé à l'opérateur (Chloé ou Sophie)

**Fonctionnement** :
1. Formulaire GET : saisie d'un email + champ confirmation = `"EFFACER"` (validation obligatoire)
2. POST : si les deux champs sont valides, `_rgpd_purge_email(email)` :
   - Supprime toutes les entrées correspondantes dans `pending.db` (base SQLite Adjoint Planning)
   - Purge les lignes contenant l'email dans `logs/recurrence_calendly.log` et `logs/recurrence_retry.log`
   - **Ne purge pas** : Notion (manuel), logs IMAP/résumés (non dans le périmètre)
3. `_rgpd_audit_log()` enregistre l'opération dans `logs/purge_rgpd.log` (IP opérateur, email, nombre de lignes supprimées)

---

## Adjoint Client

**Ce qu'il fait** : surveille les boîtes mail de Chloé, classe les emails entrants via Claude (annulations, demandes d'inscription, rattrapages), crée des entrées dans la base Notion Élèves, génère un résumé quotidien et synchronise les statuts de contrats Docage.

**Dashboard** : `automations.chloeludmann.fr/dashboard/` — bloc "Adjoint Client"

**Outils connectés** : IMAP OVH (`contact@chloeludmann.fr`) + IMAP Infomaniak (`contact@whisper-in-the-rennes.fr`), Claude AI (classification), Notion (base Élèves `35eafa74`), Docage (API signatures), Gmail SMTP (envoi résumés)

**Actions affichées dans le dashboard** :

| Action | Type | Fréquence | Script |
|---|---|---|---|
| Surveillance des boîtes mail | cron | Tous les jours à 19h30 | `imap_to_notion_chloe.py` |
| Synchronisation Docage | cron | Lun, mer, ven à 8h | `docage_to_notion.py` |
| Résumé quotidien | cron | Tous les jours à 20h | `daily_summary.py` |
| Backup Notion | cron | Dimanches à 20h | `weekly_backup.py` |
| Export Excel | systemd | Service permanent (port 5003) | `export_excel/app.py` |
| Résumé des mails | cron | Tous les jours à 19h30 | `imap_to_notion_chloe.py` |
| Fiche individuelle client | cron | Tous les jours à 19h30 | `imap_to_notion_chloe.py` |

**Logs** : `logs/imap_to_notion_chloe.log`, `logs/docage_to_notion.log`, `logs/daily_summary.log`, `logs/weekly_backup.log`

---

## Export Élèves (`export-eleves.service`)

**Ce qu'il fait** : exporte en temps réel la base Notion Élèves (`35eafa74`) en fichier Excel téléchargeable. Accessible directement depuis le dashboard Chloé (bouton "Export Excel").

**Service** : `export-eleves.service` — port 5003, permanent
**Fichier** : `automations/export_excel/app.py`

**Endpoint** : `GET /export-eleves` — sans authentification, retourne directement `eleves.xlsx`

**Fonctionnement** :
- Récupère toutes les pages de la base Notion (pagination 100/requête)
- Génère un fichier Excel via openpyxl : en-tête bleu (`2F5496`), police blanche gras, première ligne figée, largeur colonnes fixée à 20
- Colonne `Relancer` exclue (`SKIP_COLUMNS`)
- Téléchargement direct (`Content-Disposition: attachment`)

---

## Adjoint Factures

**Ce qu'il fait** : récupère les factures reçues dans les boîtes mail IMAP, les upload sur Google Drive et crée les entrées correspondantes dans la base Notion Factures.

**Dashboard** : `automations.chloeludmann.fr/dashboard/` — bloc "Adjoint Factures"

**Outils connectés** : IMAP OVH, Google Drive (dossier `1K3IRH_GEbXjDFZELfsYUNI78OaykghzY`), Notion (base Factures `327afa74`)

**Services** :

| Action | Type | Fréquence | Service / Script |
|---|---|---|---|
| Récupère les factures dans les boîtes mail et les envoie dans le Drive | cron | Lundis à 8h | `factures/factures.py` |
| Interface scan (interne, non affiché) | systemd | Permanent (port 5004) | `factures-app.service` |

**Log** : `logs/factures.log`

**Note** : le token Google OAuth (`token.json`) n'a actuellement que le scope `gmail.readonly` — le scope `drive.file` doit être ajouté pour que l'upload Drive fonctionne. Voir `reauth_drive.py`.

---

## Adjoint Attente

**Ce qu'il fait** : gère la liste d'attente de Chloé. Quand un élève s'inscrit via le formulaire Tally, il est ajouté à la liste. Quand une annulation Calendly arrive via webhook, tous les inscrits reçoivent un email de proposition de créneau.

**Dashboard** : `automations.chloeludmann.fr/dashboard/` — bloc "Adjoint Attente"

**Outils connectés** : Tally (formulaire `obBLae`, webhook `/tally`), Calendly (webhook annulation `/calendly`), Gmail SMTP

**Service** : `liste-attente.service` — port 5002, permanent

**Endpoints** :
- `POST /tally` — reçoit les inscriptions Tally
- `POST /calendly` — reçoit les annulations Calendly (`invitee.canceled`)
- `GET /unsubscribe` — désabonnement liste

**Fichiers clés** :
- `liste_attente/app.py` — webhook principal
- `liste_attente/notifier.py` — envoi emails aux inscrits
- `liste_attente/waitlist.json` — liste d'attente persistée
- `liste_attente/monitor.py` — cron quotidien 7h, vérifie que le webhook est actif

**Webhook Calendly enregistré** : `dfb337a4-9e69-46cb-8f56-fcdc3ec68a3b`

**Log** : `logs/liste_attente.log`, `logs/monitor.log`

**État** : le webhook `/calendly` crashait avec `AttributeError` (structure payload Calendly mal parsée). Corrigé : `payload["event"]` est une string URI (pas un dict) ; `start_time`/`end_time` sont récupérés via `GET /scheduled_events/{uuid}` ; `scheduling_url` depuis `payload["invitee"]["reschedule_url"]`. Try/except global ajouté.

---

## Adjoint Social

**Ce qu'il fait** : génère des contenus réseaux sociaux et newsletter via IA à partir d'un brief texte (Instagram, Facebook, LinkedIn, Newsletter), avec historique et édition inline.

**Dashboard** : `automations.chloeludmann.fr/dashboard/` — bloc "Adjoint Social"

**État** : module non encore déployé (bouton désactivé dans le dashboard). Route `/brief_to_post` prévue.

**Outils prévus** : Claude AI (génération de contenu)

---

## Adjoint Prospection (Chloé)

**Ce qu'il fait** : même module que Sophie — recherche France/Suisse/Belgique, enrichissement, base contacts SQLite, envoi emails. Déployé dans `chloe-dashboard` (port 5005, même service que le dashboard principal).

**Dashboard** : `automations.chloeludmann.fr/dashboard/` — card "Adjoint Prospection" (bouton "Ouvrir la prospection")

**Base SQLite** : `chloe-dashboard/prospection/contacts.db` — **séparée** de celle de Sophie (`sophie-dashboard/prospection/contacts.db`). Les deux bases sont indépendantes, aucune donnée n'est partagée.

**Coexistence avec la purge RGPD** : la route `POST /rgpd` dans `chloe-dashboard/app.py` est la purge des données élèves (voir section "Dashboard Chloé — Route RGPD"). Elle coexiste dans le même `app.py` que les routes Adjoint Prospection. La page d'information confidentialité est à `/politique-confidentialite` (et non `/rgpd` comme chez Sophie).

**Fichiers clés** : `chloe-dashboard/prospection/` — identiques à sophie-dashboard (scraper.py, scraper_ch.py, scraper_be.py, runner.py, enricher.py, storage.py)

**Routes** (mêmes URLs que Sophie, même comportement) :

| Méthode | Route | Description |
|---|---|---|
| GET | `/prospection` | Page principale — stats, tâche en cours, formulaire (3 onglets pays) |
| POST | `/prospection/run` | Lance une recherche (`country=FR/CH/BE`, codes NAF ou mots-clés) |
| GET | `/prospection/status` | JSON — état de la tâche en cours (polling toutes les 2s) |
| GET | `/prospection/contacts` | Liste des contacts filtrée et paginée (50/page) |
| GET | `/prospection/contacts/export.csv` | Export CSV |
| GET | `/prospection/contacts/export.xlsx` | Export Excel |
| POST | `/prospection/contacts/delete` | Suppression par IDs |
| PATCH | `/prospection/contacts/<id>` | Mise à jour inline (statut, notes) |
| GET | `/prospection/today` | Contacts ajoutés aujourd'hui |
| GET | `/prospection/priorite` | 15 contacts prioritaires |
| GET | `/prospection/funnel` | Entonnoir de conversion par statut |
| GET/POST | `/prospection/profile` | Profil expéditeur — SMTP, signature, limite quotidienne |
| GET/POST | `/contact` | Formulaire de contact (footer) |
| GET | `/politique-confidentialite` | Page RGPD & Confidentialité (≠ Sophie où c'est `/rgpd`) |

---

## Adjoint Planning

**Ce qu'il fait** : reçoit les soumissions du formulaire Tally de réservation de cours récurrents, crée automatiquement les réservations Calendly pour toute la saison (hebdomadaires ou bi-hebdomadaires), et gère un mécanisme de retry pour les créneaux encore hors de la fenêtre de 60 jours Calendly.

**Dashboard** : `automations.chloeludmann.fr/dashboard/` — bloc "Adjoint Planning"

**Outils connectés** : Tally (formulaire `VLqbG6`, webhook `/recurrence-webhook`), Calendly (API `/scheduled_events`, `/invitees`), Gmail SMTP (confirmation élève + notification Chloé)

**Services** :

| Action | Type | Fréquence | Service / Script |
|---|---|---|---|
| Réservation cours régulier | systemd | Permanent (port 5007) | `recurrence-calendly.service` |
| Retry créneaux (interne, non affiché) | cron | Tous les jours à 7h | `recurrence_calendly/retry.py` |

**Endpoints** :
- `POST /recurrence-webhook` — reçoit les soumissions Tally
- `GET /recurrence-webhook/health` — healthcheck

**Fichiers clés** :
- `recurrence_calendly/app.py` — traitement Tally + réservation Calendly
- `recurrence_calendly/retry.py` — relance quotidienne des créneaux en attente
- `recurrence_calendly/pending.db` — SQLite des créneaux en attente

**Idempotence** : `processed_forms.json` (côté `recurrence_calendly/`) enregistre les `responseId` Tally déjà traités pour éviter les doubles envois en cas de retry Tally.

**Log** : `logs/recurrence_calendly.log`, `logs/recurrence_retry.log`

**Logique `check_and_book`** :
- Appelle toujours `GET /event_type_available_times` en premier
- Si liste vide → statut `unavailable` directement (plus de logique "pending automatique")
- `WINDOW_DAYS=365` dans `.env` — conservé mais ne sert plus à classifier une réponse vide

**Fréquence paire/impaire** : le champ Tally "Type de semaines" (paires / impaires / toutes) est lu à l'entrée et converti en filtre de semaine avant d'interroger Calendly.

**SMTP** : Gmail SMTP via `boutemy.automatisation@gmail.com` (app password `GMAIL_AUTOMATION_PASSWORD`). OVH abandonné (relay silencieux). Brevo en attente d'activation.

**Charte email** :

| Rôle | Hex |
|---|---|
| Vert principal (boutons) | `#419958` |
| Rouge / alerte | `#EA4F26` |
| Rose (accents doux) | `#FFB7DD` |
| Beige fond | `#F8EFE2` |
| Noir texte | `#23242C` |

---

## Calendly — Planning de Chloé

**Schedule actif** : "Sept 2026 > Juillet 2027" (`4c8a3ac0-cffd-47b1-a9e4-afaf57bbee6a`), timezone Europe/Berlin.

**Règles de base (wday)** : lundi–samedi ouverts 09h00–20h00. Dimanche fermé. En pratique, presque chaque jour a sa propre exception `type=date` avec des horaires précis (14h–18h30 ou 09h–13h30) — c'est le vrai planning de Chloé, pas un bug.

**Vacances connues** :

| Période | Dates |
|---|---|
| Été 2026 | 4 août – 28 août 2026 |
| Toussaint 2026 | 26–30 oct 2026 |
| Noël 2026 | 20–31 déc 2026 |
| Carnaval 2027 | 1er–5 mars 2027 |
| Ascension 2027 | 9–22 mai 2027 |
| Été 2027 | À partir du 3 août 2027 |

**Source de vérité** : `GET /event_type_available_times` — seule source fiable pour les créneaux réservables.

**Event types cours réguliers** : configurés sur "Indéfiniment" (pas de date limite). Ne pas remettre de limite.

---

---

# Automatisations — Projet Sophie (Mon Adjoint IA)

Dashboard : `https://pro.mon-adjoint-ia.fr/`
Répertoire : `/home/ubuntu/sophie-dashboard/`
Service : `sophie-dashboard.service` — port 5006

**Titre header** : "Mon Adjoint IA" (affiché à côté du logo dans la navbar)
**Tagline** : "Des outils digitaux qui travaillent pour vous"
**Breakpoint mobile** : menu hamburger actif sous 1084px

---

## Site statique `mon-adjoint-ia.fr`

**Chemin VPS** : `/var/www/mon-adjoint-ia/`
**Domaine** : `mon-adjoint-ia.fr` (servi par Nginx, fichiers statiques uniquement — pas de Flask)

**Structure** :

```
/var/www/mon-adjoint-ia/
├── index.html           (28 Ko — page vitrine principale)
├── mentions-legales.html (9,8 Ko)
├── cgv.html             (12 Ko)
├── css/style.css
├── js/main.js
└── assets/img/sophie.webp
```

**`index.html`** — page vitrine de Mon Adjoint IA. Sections principales :
- Accroche : "Marre de passer vos dimanches sur la paperasse ?"
- Problèmes ciblés (H3) : journées pleines, outils dispersés, outils tout-faits inadaptés
- Processus en 3 étapes : observer le métier → construire l'agent → il travaille, vous validez
- Agents présentés (H3) : base de données client, liste d'attente, factures automatisées, prospection ciblée
- Section "Sophie Boutemy" + formulaire de contact "Regardons ensemble ce qu'on peut retirer de vos épaules"

**`mentions-legales.html`** — deux parties :
1. Mentions légales : éditeur du site, hébergement, propriété intellectuelle, données personnelles, responsabilité
2. Annexe — Accord de sous-traitance RGPD (DPA) : articles A.1 à A.9 (objet, rôles, traitements, sous-traitance ultérieure, sécurité, conservation, violations, droits des personnes, sort des données)

**`cgv.html`** — 10 articles : identification prestataire, objet, description des services (catalogue agents + caractère évolutif), tarifs, maintenance mensuelle (contenu inclus / exclusions / hébergement alternatif), garantie de bon fonctionnement, obligations client, durée et résiliation, responsabilité, droit applicable.

Ces deux pages sont liées depuis le footer des deux dashboards (`https://mon-adjoint-ia.fr/mentions-legales.html`, `https://mon-adjoint-ia.fr/cgv.html`).

---

## Interface — éléments communs (Sophie ET Chloé)

Les éléments suivants sont présents sur **les deux dashboards** (`sophie-dashboard/templates/base.html` et `chloe-dashboard/templates/base.html`) :

- **Footer global** : Mentions légales (→ `https://mon-adjoint-ia.fr/mentions-legales.html`), CGV (→ `https://mon-adjoint-ia.fr/cgv.html`), RGPD, Contact, sophieboutemy.fr, mon-adjoint-ia.fr. Copyright via context_processor `inject_year`. Lien RGPD → `/rgpd` chez Sophie (page info), `/politique-confidentialite` chez Chloé (la route `/rgpd` de Chloé étant la purge élèves).
- **Menu hamburger** : breakpoint 1084px (`@media (max-width: 1083px)`), bouton `.nav-hamburger`, toggle JS inline dans `base.html`.
- **Icône déconnexion** : SVG logout dans `.nav-logout`, pas de texte "Déconnexion".
- **Tagline** : "Des outils digitaux qui travaillent pour vous" sous le logo (les deux dashboards).
- **Sous-menu Adjoint Prospection** : présent sur toutes les pages du module (`prospection`, `contacts`, `today`, `funnel`, `priorite`, `profile`). Bouton "Contacts" à gauche (orange), trois boutons "Profil expéditeur / À traiter / Entonnoir" groupés à droite avec état actif. Lien retour "← Tableau de bord Adjoint Prospection" sous le titre, sauf sur la page principale.

---

## Adjoint Prospection

**Ce qu'il fait** : recherche d'entreprises par codes NAF/département (France), mots-clés/cantons (Suisse), mots-clés/provinces (Belgique), enrichissement automatique (site web + email), gestion d'une base de contacts avec statuts, notes, export CSV/XLSX, rédaction et envoi d'emails de prospection.

**Dashboard** : `pro.mon-adjoint-ia.fr` — module "Adjoint Prospection"

**Pays supportés** :
- 🇫🇷 France — API Annuaire Entreprises (`recherche-entreprises.api.gouv.fr`), codes NAF, filtre département et taille
- 🇨🇭 Suisse — API Zefix REST (`zefix.ch`), mots-clés, filtre canton — `prospection/scraper_ch.py`
- 🇧🇪 Belgique — API KBO/BCE (`api.kbo-bce.fgov.be`), mots-clés, filtre province — `prospection/scraper_be.py`

**Logique de recherche** : `runner.py` boucle jusqu'à obtenir N contacts **valides** (avec `site_web` ou `email`) — pas seulement N entreprises brutes. La boucle s'arrête si l'API est épuisée.

**Routes principales** :

| Méthode | Route | Description |
|---|---|---|
| GET | `/prospection` | Page principale — stats, tâche en cours, formulaire (3 onglets pays) |
| POST | `/prospection/run` | Lance une recherche (`country=FR/CH/BE`, codes NAF ou mots-clés) |
| GET | `/prospection/status` | JSON — état de la tâche en cours (polling toutes les 2s) |
| GET | `/prospection/contacts` | Liste des contacts filtrée et paginée (50/page) |
| GET | `/prospection/contacts/export.csv` | Export CSV |
| GET | `/prospection/contacts/export.xlsx` | Export Excel |
| POST | `/prospection/contacts/delete` | Suppression par IDs |
| PATCH | `/prospection/contacts/<id>` | Mise à jour inline (statut, notes) |
| GET | `/prospection/today` | Contacts ajoutés aujourd'hui — liste avec actions d'envoi |
| GET | `/prospection/priorite` | 15 contacts prioritaires (statuts actifs) — quota SMTP affiché |
| GET | `/prospection/funnel` | Entonnoir de conversion par statut |
| GET/POST | `/prospection/profile` | Profil expéditeur — nom, activité, signature, config SMTP, limite quotidienne |
| GET | `/rgpd` | Page RGPD & Confidentialité (template `rgpd.html`) |
| GET/POST | `/contact` | Formulaire de contact → `contact@sophieboutemy.fr` via OVH SMTP |

**Fichiers clés** :
- `app.py` — Flask principal (port 5006)
- `config.json` — agents IA et clients (données du tableau de bord)
- `prospection/scraper.py` — API Annuaire Entreprises (France)
- `prospection/scraper_ch.py` — API Zefix (Suisse)
- `prospection/scraper_be.py` — API KBO/BCE (Belgique)
- `prospection/enricher.py` — enrichissement site + email
- `prospection/storage.py` — CRUD SQLite
- `prospection/runner.py` — thread background + `task_status.json`, fonctions `start_search`, `start_search_ch`, `start_search_be`
- `prospection/contacts.db` — base SQLite des contacts

**Statuts contacts** : `nouveau`, `qualifié`, `contacté`, `répondu`, `écarté`

**Upsert** : sur SIREN — en cas de conflit, ne met à jour que site/email si la nouvelle valeur n'est pas vide.

**config.json** : pilote le contenu du tableau de bord. `status: "active"` → bouton URL visible ; `status: "coming_soon"` → badge "Bientôt disponible".

**Carte Chloé Ludmann** (`_CLIENT_CHECKS` dans `app.py`) : affiche les 5 automations actives de Chloé avec leur statut temps réel — Adjoint Client (log), Adjoint Factures (log), Adjoint Attente (systemd), Adjoint Planning (systemd), Adjoint Prospection (systemd `chloe-dashboard.service`).

**Crons** : aucun — service uniquement piloté par systemd.

### Route `/prospection/profile` — profil expéditeur

**Accès** : `@login_required` — `GET/POST`

Formulaire de configuration de l'identité et du canal d'envoi. Données persistées dans `sophie-dashboard/profil_expediteur.json` (chargé/sauvegardé via `prospection/drafter.py` → `load_profile` / `save_profile`).

**Champs sauvegardés** :

| Champ | Usage |
|---|---|
| `prenom` / `nom` | Nom affiché dans les emails sortants |
| `activite` | Secteur / métier de Sophie (contexte IA) |
| `proposition_valeur` | Accroche de valeur pour la rédaction IA |
| `offre` | Offre principale proposée |
| `signature` | Bloc signature HTML des emails |
| `smtp_host` / `smtp_port` | Serveur SMTP (défaut `ssl0.ovh.net` / `465`) |
| `smtp_user` / `smtp_pass` | Credentials SMTP — le mot de passe est préservé si le champ est laissé vide en édition |
| `smtp_daily_limit` | Quota d'envoi quotidien (défaut `50`) — partagé entre `/prospection/priorite`, `/prospection/today` et l'envoi inline |

Le quota consommé du jour est calculé séparément par `_get_quota()` et affiché sur le formulaire.

### Route `/rgpd` — page d'information

**Accès** : public (pas de `@login_required`) — `GET`

Affiche le template `rgpd.html` : politique de confidentialité et mentions légales RGPD du service. Lien du footer. À distinguer de la route `/rgpd` de Chloé qui est la **purge élèves** (`POST`, protégée).

### Route `/contact` — formulaire de contact

**Accès** : public — `GET/POST`

Formulaire de contact footer. En POST, envoie un email via OVH SMTP SSL port 465 (`ssl0.ovh.net`), depuis `IMAP_EMAIL` (`contact@chloeludmann.fr`), vers `contact@sophieboutemy.fr`.

**Reset mot de passe** : token signé via `itsdangerous` (1h), envoi SMTP OVH SSL port 465 (`ssl0.ovh.net`).
