#!/usr/bin/env python3
"""
purge_anciens.py - Archive prospection contacts with no response for 12+ months.

Usage (from dashboard root):
    python3 prospection/purge_anciens.py           # dry-run: shows what would change
    python3 prospection/purge_anciens.py --apply   # actually archive
    python3 prospection/purge_anciens.py --months 6   # custom threshold
"""
import argparse
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contacts.db')

STATUTS_ARCHIVABLES = (
    'nouveau', 'qualifié', 'contacté', '1er contact',
    'proposition', 'relancé', 'suivi', 'injoignable',
)


def run(apply=False, months=12):
    if not os.path.exists(DB_PATH):
        print(f"Base introuvable : {DB_PATH}")
        return 0

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    placeholders = ','.join('?' * len(STATUTS_ARCHIVABLES))
    rows = conn.execute(f"""
        SELECT id, nom_entreprise, statut,
               COALESCE(NULLIF(date_maj, ''), date_collecte) AS ref_date
        FROM contacts
        WHERE statut IN ({placeholders})
          AND date(COALESCE(NULLIF(date_maj, ''), date_collecte)) <= date('now', '-{months} months')
    """, STATUTS_ARCHIVABLES).fetchall()

    if not rows:
        print(f"Aucun contact sans réponse depuis {months} mois.")
        conn.close()
        return 0

    label = 'DRY-RUN' if not apply else 'ARCHIVAGE'
    print(f"{label} — {len(rows)} contact(s) concerné(s) (seuil : {months} mois) :\n")
    for r in rows:
        ref = (r['ref_date'] or '?')[:10]
        nom = (r['nom_entreprise'] or '?')[:45]
        print(f"  [{r['id']:5d}] {nom:<45}  statut={r['statut']:<15}  ref={ref}")

    if apply:
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        ids = [r['id'] for r in rows]
        conn.execute(
            f"UPDATE contacts SET statut='archivé', date_maj=? "
            f"WHERE id IN ({','.join('?'*len(ids))})",
            [now] + ids,
        )
        conn.commit()
        print(f"\n{len(rows)} contact(s) passé(s) en statut \'archivé\'.")
    else:
        print(f"\nRelancez avec --apply pour archiver ces {len(rows)} contact(s).")

    conn.close()
    return len(rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Archive contacts sans réponse depuis N mois."
    )
    parser.add_argument('--apply', action='store_true',
                        help="Appliquer l'archivage (sans ce flag : dry-run)")
    parser.add_argument('--months', type=int, default=12,
                        help="Seuil en mois (défaut : 12)")
    args = parser.parse_args()
    run(apply=args.apply, months=args.months)
