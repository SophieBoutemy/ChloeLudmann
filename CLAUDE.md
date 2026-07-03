# ~/chloe-automations — statut

**Ce dossier n'est pas encore la source active.** C'est une copie en cours de constitution de la partie Chloé Ludmann de `~/automations`, créée par copie non destructive (`cp -a`), en vue d'une future séparation des deux projets hébergés sur ce VPS.

- **Source de référence actuelle** : `~/automations` (voir `~/automations/CLAUDE.md`, section "Séparation ~/automations (en cours)"). Tant que la séparation n'est pas validée, c'est `~/automations` qui fait foi — cron `backup_complet.sh` (dimanche 21h) y reste branché.
- **Contenu** : `chloe-dashboard/`, `factures/`, `liste_attente/`, `recurrence_calendly/`, `export_excel/`, `scripts/gmail_notion_classification.py`, scripts racine Chloé (Gmail/Notion, tests, diagnostics, brouillons mailchimp/newsletter), `backups/`, `logs/` (hors fichiers liés à Mon Adjoint IA).
- **`.env`** : version filtrée, 23 clés utilisées par le code Chloé uniquement (extraites de `~/automations/.env`). Permissions `600`.
- **GitHub** : destiné au repo `chloeludmann` sur le compte `SophieBoutemy` (`https://github.com/SophieBoutemy/chloeludmann.git`) — **créé mais pas encore poussé**.
- **Pas encore fait** : `git init`, premier commit, push, bascule des crons/services depuis `~/automations` vers ce dossier.
