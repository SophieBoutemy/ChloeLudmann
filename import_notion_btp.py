#!/usr/bin/env python3
"""
Import one-shot depuis la base Notion "Brief to Post" vers brief_to_post.db.
A exécuter une seule fois après déploiement, puis archiver ou supprimer.
"""

import os
import sqlite3
import uuid
import requests
from dotenv import load_dotenv

load_dotenv('/home/ubuntu/automations/.env')

NOTION_API_KEY = os.getenv('NOTION_API_KEY', '')
NOTION_BTP_DB  = '318afa74cfc981148528e6791c72f1cc'
NOTION_BASE    = 'https://api.notion.com/v1'
SQLITE_PATH    = '/home/ubuntu/automations/chloe-dashboard/brief_to_post.db'


def _hdrs():
    return {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Notion-Version': '2022-06-28',
        'Content-Type': 'application/json',
    }


def _prop(prop):
    t = prop.get('type', '')
    if t == 'title':
        return ''.join(r['plain_text'] for r in prop.get('title', []))
    if t == 'rich_text':
        return ''.join(r['plain_text'] for r in prop.get('rich_text', []))
    if t == 'select':
        s = prop.get('select')
        return s['name'] if s else ''
    if t == 'date':
        d = prop.get('date')
        return d['start'] if d else ''
    return ''


def fetch_all_pages():
    url = f'{NOTION_BASE}/databases/{NOTION_BTP_DB}/query'
    results, cursor = [], None
    while True:
        body = {'page_size': 100}
        if cursor:
            body['start_cursor'] = cursor
        r = requests.post(url, headers=_hdrs(), json=body, timeout=15)
        r.raise_for_status()
        data = r.json()
        results.extend(data.get('results', []))
        print(f'  Récupéré {len(results)} pages...', end='\r')
        if not data.get('has_more'):
            break
        cursor = data.get('next_cursor')
    print()
    return results


def get_db():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('''CREATE TABLE IF NOT EXISTS posts (
        id         TEXT PRIMARY KEY,
        titre      TEXT DEFAULT '',
        brief      TEXT NOT NULL,
        ton        TEXT NOT NULL,
        reseau     TEXT NOT NULL,
        texte      TEXT DEFAULT '',
        statut     TEXT DEFAULT 'Généré',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    return conn


def main():
    if not NOTION_API_KEY:
        print('ERREUR : NOTION_API_KEY manquant dans .env')
        return

    print(f'Connexion à Notion DB {NOTION_BTP_DB}...')
    pages = fetch_all_pages()
    print(f'{len(pages)} pages trouvées dans Notion.')

    conn = get_db()
    imported = skipped_status = skipped_dup = skipped_empty = 0

    for page in pages:
        props = page.get('properties', {})

        statut = _prop(props.get('Statut', {}))
        if statut != 'Généré':
            skipped_status += 1
            continue

        titre    = _prop(props.get('Titre', {}))
        brief    = _prop(props.get('Brief', {}))
        ton      = _prop(props.get('Ton', {}))
        reseau   = _prop(props.get('Réseau', {}))
        texte    = _prop(props.get('Texte généré', {}))
        date_gen = _prop(props.get('Date de génération', {}))

        if not brief:
            skipped_empty += 1
            continue

        # Dédup : même titre + même date de génération
        dedup_date = date_gen or '1970-01-01'
        existing = conn.execute(
            'SELECT id FROM posts WHERE titre = ? AND date(created_at) = date(?)',
            (titre, dedup_date),
        ).fetchone()
        if existing:
            skipped_dup += 1
            continue

        created_at = f'{date_gen}T12:00:00' if date_gen else None

        conn.execute(
            '''INSERT INTO posts (id, titre, brief, ton, reseau, texte, statut, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'Généré', ?)''',
            (str(uuid.uuid4()), titre, brief, ton or '', reseau or '', texte or '', created_at),
        )
        imported += 1

    conn.commit()
    conn.close()

    print()
    print('─' * 50)
    print(f'Import terminé.')
    print(f'  ✓ Importées     : {imported}')
    print(f'  ○ Doublons      : {skipped_dup}')
    print(f'  ○ Statut ignoré : {skipped_status}  (pas "Généré")')
    print(f'  ○ Brief vide    : {skipped_empty}')
    print('─' * 50)


if __name__ == '__main__':
    main()
