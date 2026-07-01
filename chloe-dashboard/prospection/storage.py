import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'contacts.db')

EXPORT_COLS = [
    'siren', 'nom_entreprise', 'nom_dirigeant', 'naf', 'activite',
    'adresse', 'code_postal', 'ville', 'departement', 'date_creation',
    'tranche_effectif', 'date_rappel', 'date_premier_contact', 'date_relance',
    'site_web', 'site_web_statut', 'email', 'email_statut', 'email_type',
    'statut', 'notes', 'date_collecte',
]


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS contacts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            siren            TEXT UNIQUE,
            nom_entreprise   TEXT,
            nom_dirigeant    TEXT DEFAULT '',
            naf              TEXT,
            activite         TEXT,
            adresse          TEXT DEFAULT '',
            code_postal      TEXT DEFAULT '',
            ville            TEXT DEFAULT '',
            departement      TEXT DEFAULT '',
            date_creation    TEXT DEFAULT '',
            tranche_effectif TEXT DEFAULT '',
            site_web         TEXT DEFAULT '',
            site_web_statut  TEXT DEFAULT '',
            email            TEXT DEFAULT '',
            email_statut     TEXT DEFAULT '',
            email_type       TEXT DEFAULT '',
            statut           TEXT DEFAULT 'nouveau',
            notes            TEXT DEFAULT '',
            date_rappel      TEXT DEFAULT NULL,
            date_premier_contact TEXT DEFAULT NULL,
            date_relance     TEXT DEFAULT NULL,
            date_collecte    TEXT,
            date_maj         TEXT
        )
    ''')
    for col_def in (
        "email_statut TEXT DEFAULT ''",
        "site_web_statut TEXT DEFAULT ''",
        "date_creation TEXT DEFAULT ''",
        "tranche_effectif TEXT DEFAULT ''",
        "date_rappel TEXT DEFAULT NULL",
        "email_type TEXT DEFAULT ''",
        "date_premier_contact TEXT DEFAULT NULL",
        "date_relance TEXT DEFAULT NULL",
    ):
        try:
            conn.execute(f'ALTER TABLE contacts ADD COLUMN {col_def}')
            conn.commit()
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def is_desinscrit(siren='', email=''):
    """Return True if a contact with this SIREN or email is already marked désinscrit."""
    parts, params = [], []
    if siren:
        parts.append('siren=?'); params.append(siren)
    if email:
        parts.append('email=?'); params.append(email)
    if not parts:
        return False
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute(
        f"SELECT COUNT(*) FROM contacts WHERE statut='désinscrit' AND ({' OR '.join(parts)})",
        params,
    ).fetchone()[0]
    conn.close()
    return n > 0


def upsert_contact(contact):
    """Insert or update a contact. Returns 'created', 'updated', or None if skipped."""
    if is_desinscrit(contact.get('siren', ''), contact.get('email', '')):
        return None
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    conn = sqlite3.connect(DB_PATH)
    try:
        exists = conn.execute(
            'SELECT id FROM contacts WHERE siren=?', (contact['siren'],)
        ).fetchone() is not None
        conn.execute('''
            INSERT INTO contacts
                (siren, nom_entreprise, nom_dirigeant, naf, activite,
                 adresse, code_postal, ville, departement, date_creation,
                 tranche_effectif,
                 site_web, site_web_statut, email, email_statut, email_type, date_collecte, date_maj)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(siren) DO UPDATE SET
                date_creation    = CASE WHEN excluded.date_creation    != '' THEN excluded.date_creation    ELSE date_creation    END,
                tranche_effectif = CASE WHEN excluded.tranche_effectif != '' THEN excluded.tranche_effectif ELSE tranche_effectif END,
                site_web         = CASE WHEN excluded.site_web         != '' THEN excluded.site_web         ELSE site_web         END,
                site_web_statut  = CASE WHEN excluded.site_web         != '' THEN excluded.site_web_statut  ELSE site_web_statut  END,
                email            = CASE WHEN excluded.email            != '' THEN excluded.email            ELSE email            END,
                email_statut     = CASE WHEN excluded.email_statut     != '' THEN excluded.email_statut     ELSE email_statut     END,
                email_type       = CASE WHEN excluded.email_type       != '' THEN excluded.email_type       ELSE email_type       END,
                date_maj         = excluded.date_maj
        ''', (
            contact['siren'], contact['nom_entreprise'],
            contact.get('nom_dirigeant', ''),
            contact['naf'], contact['activite'],
            contact.get('adresse', ''), contact.get('code_postal', ''),
            contact.get('ville', ''), contact.get('departement', ''),
            contact.get('date_creation', ''),
            contact.get('tranche_effectif', ''),
            contact.get('site_web', ''), contact.get('site_web_statut', ''),
            contact.get('email', ''), contact.get('email_statut', ''),
            contact.get('email_type', ''),
            now, now,
        ))
        conn.commit()
        return 'updated' if exists else 'created'
    finally:
        conn.close()


def get_contacts(statut=None, naf=None, tranche=None, search=None,
                 limit=50, offset=0, include_unsubscribed=False,
                 rappel_echu=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    q = "SELECT * FROM contacts WHERE 1=1"
    params = []
    if not include_unsubscribed:
        q += " AND statut NOT IN ('désinscrit', 'archivé')"
    if statut:
        q += ' AND statut=?'; params.append(statut)
    if naf:
        q += ' AND naf=?'; params.append(naf)
    if tranche:
        q += ' AND tranche_effectif=?'; params.append(tranche)
    if search:
        q += ' AND (nom_entreprise LIKE ? OR nom_dirigeant LIKE ? OR ville LIKE ? OR email LIKE ?)'
        params += [f'%{search}%'] * 4
    if rappel_echu:
        today = datetime.now().strftime('%Y-%m-%d')
        q += ' AND date_rappel IS NOT NULL AND date_rappel <= ?'
        params.append(today)
    total = conn.execute(q.replace('SELECT *', 'SELECT COUNT(*)'), params).fetchone()[0]
    q += ' ORDER BY date_collecte DESC LIMIT ? OFFSET ?'
    rows = conn.execute(q, params + [limit, offset]).fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def get_contact_by_id(contact_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM contacts WHERE id=?', (contact_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_stats():
    conn = sqlite3.connect(DB_PATH)
    stats = {
        'total':      conn.execute("SELECT COUNT(*) FROM contacts WHERE statut NOT IN ('désinscrit', 'archivé')").fetchone()[0],
        'avec_email': conn.execute("SELECT COUNT(*) FROM contacts WHERE email != '' AND statut NOT IN ('désinscrit', 'archivé')").fetchone()[0],
        'avec_site':  conn.execute("SELECT COUNT(*) FROM contacts WHERE site_web != '' AND statut NOT IN ('désinscrit', 'archivé')").fetchone()[0],
        'contactes':  conn.execute(
            "SELECT COUNT(*) FROM contacts WHERE statut IN ('contacté','1er contact','proposition','relancé','suivi','répondu','rdv','injoignable')"
        ).fetchone()[0],
        'par_naf': {},
    }
    for r in conn.execute("SELECT naf, activite, COUNT(*) FROM contacts WHERE statut NOT IN ('désinscrit', 'archivé') GROUP BY naf ORDER BY naf"):
        stats['par_naf'][r[0]] = {'activite': r[1], 'count': r[2]}
    conn.close()
    return stats


def get_funnel_stats():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute('SELECT statut, COUNT(*) FROM contacts GROUP BY statut').fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


def get_today_contacts():
    today = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM contacts WHERE date_collecte LIKE ? AND statut NOT IN ('désinscrit', 'archivé') ORDER BY date_collecte DESC",
        (f'{today}%',)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_naf_list():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT DISTINCT naf, activite FROM contacts WHERE statut NOT IN ('désinscrit', 'archivé') ORDER BY naf").fetchall()
    conn.close()
    return [{'naf': r[0], 'activite': r[1]} for r in rows]


def get_tranche_list():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT DISTINCT tranche_effectif FROM contacts WHERE tranche_effectif != '' ORDER BY tranche_effectif"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_priorite_contacts(limit=15):
    """Return top contacts sorted by priority score."""
    from .scorer import compute_score
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT * FROM contacts
           WHERE statut NOT IN ('désinscrit','archivé','converti','écarté','pas intéressé','injoignable')
           AND (email != '' OR site_web != '')"""
    ).fetchall()
    conn.close()
    contacts = [dict(r) for r in rows]
    for c in contacts:
        c['_score'] = compute_score(c)
    contacts.sort(key=lambda x: x['_score'], reverse=True)
    return contacts[:limit]


def update_contact(contact_id, updates):
    allowed = {'statut', 'notes', 'site_web', 'site_web_statut',
                'email', 'email_statut', 'email_type', 'date_rappel',
                'date_premier_contact', 'date_relance'}
    sets = {k: v for k, v in updates.items() if k in allowed}
    if not sets:
        return
    sets['date_maj'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    q = 'UPDATE contacts SET ' + ', '.join(f'{k}=?' for k in sets) + ' WHERE id=?'
    conn = sqlite3.connect(DB_PATH)
    conn.execute(q, list(sets.values()) + [contact_id])
    conn.commit()
    conn.close()


def delete_contacts(ids):
    if not ids:
        return 0
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        f'DELETE FROM contacts WHERE id IN ({",".join("?" * len(ids))})',
        [int(i) for i in ids],
    ).rowcount
    conn.commit()
    conn.close()
    return rows


def delete_contacts_empty():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "DELETE FROM contacts WHERE site_web = '' AND email = ''"
    ).rowcount
    conn.commit()
    conn.close()
    return rows


def get_filtered_for_export(statut=None, naf=None, tranche=None, search=None):
    """Export with active filters applied."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    q = f"SELECT {', '.join(EXPORT_COLS)} FROM contacts WHERE statut NOT IN ('désinscrit', 'archivé')"
    params = []
    if statut:
        q += ' AND statut=?'; params.append(statut)
    if naf:
        q += ' AND naf=?'; params.append(naf)
    if tranche:
        q += ' AND tranche_effectif=?'; params.append(tranche)
    if search:
        q += ' AND (nom_entreprise LIKE ? OR nom_dirigeant LIKE ? OR ville LIKE ? OR email LIKE ?)'
        params += [f'%{search}%'] * 4
    rows = conn.execute(q + ' ORDER BY date_collecte DESC', params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_for_export():
    return get_filtered_for_export()
