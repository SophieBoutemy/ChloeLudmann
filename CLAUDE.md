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
sudo systemctl restart <service>
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

---

## GitHub

**⚠️ Ancien compte `lapetitefabriquedigitale`** : le token utilisé pour ce compte a été **compromis (exposé en clair dans une sortie de commande) et révoqué**. Ne plus jamais l'utiliser ni tenter de le régénérer sur ce compte pour de nouvelles opérations.

Repos historiques encore actifs sous ce compte (non migrés) :
- **ChloeLudmann** — `https://github.com/lapetitefabriquedigitale/ChloeLudmann.git` — dans `~/automations`, **toujours utilisé par le cron `backup_complet.sh` (dimanche 21h)**. Ne pas repointer ce remote sans validation explicite, ce cron est en production.
- **MonEspacePro** — `https://github.com/lapetitefabriquedigitale/MonEspacePro.git` — dans `~/sophie-dashboard`.

**Nouveau compte GitHub : `SophieBoutemy`**
- Authentification via `credential.helper store` : token stocké dans `~/.git-credentials` (permissions `600`), **jamais** embarqué en clair dans une URL de remote (`git remote -v` reste toujours propre).
- Repos actifs :
  - **monadjointia** — `https://github.com/SophieBoutemy/monadjointia.git` — `/var/www/mon-adjoint-ia`
  - **lpfd** — `https://github.com/SophieBoutemy/lpfd.git` — `~/sites-statiques/lapetitefabriquedigitale`
  - **chloeludmann** — créé sur `SophieBoutemy` mais **pas encore peuplé** — la séparation de `~/automations` est en cours (voir section "Séparation ~/automations" ci-dessous), ce repo recevra `~/chloe-automations` une fois la validation faite.
- **Branche** : `master` (nouveaux repos) — à distinguer de `main` utilisé par les anciens repos `lapetitefabriquedigitale`.

---

## Séparation `~/automations` (en cours, pas encore finalisée)

`~/automations` contient historiquement le code de Chloé Ludmann **et** quelques traces de Mon Adjoint IA (Sophie) mélangées (2 fichiers de logs). Une séparation par **copie non destructive** est en cours :

- **`~/automations`** — reste la source active et de référence. **Non touché**, le cron `backup_complet.sh` (dimanche 21h) continue de tourner dessus normalement pendant toute l'opération.
- **`~/chloe-automations/`** — copie en cours de constitution, contiendra à terme tout ce qui est spécifique à Chloé Ludmann : `chloe-dashboard/`, `factures/`, `liste_attente/`, `recurrence_calendly/`, `export_excel/`, scripts Gmail/Notion (`imap_to_notion_chloe.py`, `daily_summary.py`, `docage_to_notion.py`, etc.), tests/diagnostics associés (`test_*.py`, `_diag_*.py`, `debug_*.py`). Un `.env` spécifique a été extrait (voir ci-dessous). Pas encore poussé vers le repo GitHub `chloeludmann`.
- **`~/autres-clients/`** — `import_notion_btp.py` (client BTP ponctuel, sans lien avec Chloé ni Mon Adjoint IA).
- **`~/a-trancher/`** — `_diag_sophie.py`, contenu non lu en détail, classement à clarifier avant de le ranger définitivement.
- **`dashboard.log`** et **`purge_anciens_sophie.log`** restent dans `~/automations/logs/` — liés à Mon Adjoint IA (Sophie), mais aucun dossier dédié type `~/sophie-automations` n'a encore été créé pour les accueillir.
- **`.env`** — reste partagé entre les deux projets dans `~/automations/.env`, pas dupliqué tel quel. Un `.env` filtré, contenant uniquement les clés effectivement utilisées par les scripts Chloé, a été créé dans `~/chloe-automations/.env` (permissions `600`).

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
| `SOPHIE_DASHBOARD_USER` | Login admin Mon Espace Pro |
| `SOPHIE_DASHBOARD_PASSWORD` | Mot de passe admin Mon Espace Pro |
| `SOPHIE_DASHBOARD_EMAIL` | Email admin Mon Espace Pro |
| `SOPHIE_DASHBOARD_SECRET_KEY` | Clé secrète Flask (sophie-dashboard) |
| `VPS_URL` | URL publique du VPS |

---

---

# Automatisations — Projet Chloé Ludmann

Dashboard : `https://automations.chloeludmann.fr/dashboard/`
Répertoire : `/home/ubuntu/automations/`

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

# Automatisations — Projet Sophie (Mon Espace Pro)

Dashboard : `https://pro.mon-adjoint-ia.fr/`
Répertoire : `/home/ubuntu/sophie-dashboard/`
Service : `sophie-dashboard.service` — port 5006

---

## Adjoint Prospection

**Ce qu'il fait** : recherche d'entreprises par codes NAF et département via l'API Annuaire Entreprises (données ouvertes), enrichissement automatique (site web + email par scraping BeautifulSoup4), gestion d'une base de contacts avec statuts, notes, export CSV.

**Dashboard** : `pro.mon-adjoint-ia.fr` — module "Adjoint Prospection"

**Outils connectés** : API Annuaire Entreprises (sans clé), BeautifulSoup4 (scraping), SQLite (`prospection/contacts.db`)

**Routes principales** :

| Méthode | Route | Description |
|---|---|---|
| GET | `/prospection` | Page principale — stats, tâche en cours, formulaire |
| POST | `/prospection/run` | Lance une recherche (codes NAF, départements, max résultats) |
| GET | `/prospection/status` | JSON — état de la tâche en cours (polling toutes les 2s) |
| GET | `/prospection/contacts` | Liste des contacts filtrée et paginée (50/page) |
| GET | `/prospection/contacts/export.csv` | Export CSV |
| POST | `/prospection/contacts/delete` | Suppression par IDs |
| PATCH | `/prospection/contacts/<id>` | Mise à jour inline (statut, notes) |

**Fichiers clés** :
- `app.py` — Flask principal (port 5006)
- `config.json` — agents IA et clients (données du tableau de bord)
- `prospection/scraper.py` — API Annuaire Entreprises
- `prospection/enricher.py` — enrichissement site + email
- `prospection/storage.py` — CRUD SQLite
- `prospection/runner.py` — thread background + `task_status.json`
- `prospection/contacts.db` — base SQLite des contacts

**Statuts contacts** : `nouveau`, `qualifié`, `contacté`, `répondu`, `écarté`

**Upsert** : sur SIREN — en cas de conflit, ne met à jour que site/email si la nouvelle valeur n'est pas vide.

**config.json** : pilote le contenu du tableau de bord. `status: "active"` → bouton URL visible ; `status: "coming_soon"` → badge "Bientôt disponible".

**Crons** : aucun — service uniquement piloté par systemd.

**Reset mot de passe** : token signé via `itsdangerous` (1h), envoi SMTP OVH SSL port 465 (`ssl0.ovh.net`).
