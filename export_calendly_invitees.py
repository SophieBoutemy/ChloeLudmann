#!/usr/bin/env python3
"""
export_calendly_invitees.py
Exporte en CSV les invités Calendly (compte Chloé Ludmann) ayant réservé un
cours à partir du 1er septembre 2026, dédoublonnés par email (on garde la
date du premier cours réservé sur cette période).

Réutilise CalendlyClient et collect_first_bookings de calendly_sync_eleves.py
(même logique de filtre de date, pagination, parallélisation et cooldown).

Usage:
    python export_calendly_invitees.py
"""

import csv
import os
from datetime import date, datetime

from calendly_sync_eleves import CalendlyClient, MIN_START_TIME, PARIS_TZ, collect_first_bookings, log

EXPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")


def local_datetime(start_time_iso: str) -> str:
    dt_local = datetime.fromisoformat(start_time_iso.replace("Z", "+00:00")).astimezone(PARIS_TZ)
    return dt_local.strftime("%Y-%m-%d %H:%M")


def main() -> None:
    calendly = CalendlyClient()
    bookings = collect_first_bookings(calendly, MIN_START_TIME)

    os.makedirs(EXPORT_DIR, exist_ok=True)
    filepath = os.path.join(EXPORT_DIR, f"calendly_invitees_{date.today().isoformat()}.csv")

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["email", "prenom", "nom", "date_premier_cours"])
        for booking in sorted(bookings.values(), key=lambda b: b["start_time"]):
            writer.writerow([
                booking["email"],
                booking["first_name"],
                booking["last_name"],
                local_datetime(booking["start_time"]),
            ])

    log.info(f"Export terminé : {len(bookings)} invité(s) unique(s) -> {filepath}")


if __name__ == "__main__":
    main()
