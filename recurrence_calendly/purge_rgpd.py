#!/usr/bin/env python3
"""
recurrence_calendly/purge_rgpd.py
Cron mensuel (1er du mois à 3h) — purge automatique des données de réservation
récurrente conformément à la politique de rétention RGPD.

Supprime de pending.db les créneaux dont la date est passée depuis plus de
RETENTION_MONTHS mois, et purge les lignes correspondantes dans les logs.
Trace chaque opération dans logs/purge_rgpd.log.
"""

import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta

# ── Config ────────────────────────────────────────────────────────────────────

RETENTION_MONTHS = 12  # Durée de conservation (mois)
RETENTION_DAYS   = RETENTION_MONTHS * 30

DB_PATH   = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pending.db')
LOG_FILES = [
    '/home/ubuntu/automations/logs/recurrence_calendly.log',
    '/home/ubuntu/automations/logs/recurrence_retry.log',
]
PURGE_LOG = '/home/ubuntu/automations/logs/purge_rgpd.log'

LOG_TS_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(PURGE_LOG),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ── Purge pending.db ──────────────────────────────────────────────────────────

def purge_pending_db(cutoff: datetime) -> int:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.execute(
            "DELETE FROM pending WHERE dt_utc < ?",
            (cutoff.strftime('%Y-%m-%dT%H:%M:%S'),),
        )
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return deleted
    except FileNotFoundError:
        return 0
    except Exception as e:
        log.error(f"Erreur purge pending.db : {e}")
        return 0


# ── Purge lignes de log plus anciennes que cutoff ─────────────────────────────

def purge_log_file(path: str, cutoff: datetime) -> int:
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return 0
    except Exception as e:
        log.error(f"Erreur lecture {path} : {e}")
        return 0

    kept    = []
    removed = 0
    for line in lines:
        m = LOG_TS_RE.match(line)
        if m:
            try:
                line_dt = datetime.strptime(m.group(1), '%Y-%m-%d')
                if line_dt < cutoff:
                    removed += 1
                    continue
            except ValueError:
                pass
        kept.append(line)

    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(kept)
    except Exception as e:
        log.error(f"Erreur écriture {path} : {e}")
        return 0

    return removed


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    log.info(
        f"=== Purge RGPD mensuelle — seuil : {cutoff.strftime('%Y-%m-%d')} "
        f"(rétention {RETENTION_MONTHS} mois) ==="
    )

    n_db = purge_pending_db(cutoff)
    log.info(f"pending.db : {n_db} entrée(s) supprimée(s)")

    for path in LOG_FILES:
        n = purge_log_file(path, cutoff)
        log.info(f"{os.path.basename(path)} : {n} ligne(s) supprimée(s)")

    log.info("=== Purge terminée ===")


if __name__ == '__main__':
    main()
