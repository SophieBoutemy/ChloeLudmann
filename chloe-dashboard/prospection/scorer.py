from datetime import date


def compute_score(contact):
    """Score 0-100 : qualité email + site + ancienneté structure + disponibilité CRM."""
    score = 0

    # Email quality (0-30)
    es = contact.get('email_statut', '')
    if es == 'vérifié':
        score += 30
    elif es == 'à risque':
        score += 10

    # Site web presence (0-20)
    if contact.get('site_web'):
        score += 20

    # Statut CRM readiness (0-30) — prioritise untouched / early-stage contacts
    statut_pts = {
        'nouveau': 30, 'qualifié': 25,
        '1er contact': 15, 'proposition': 10,
        'relancé': 8, 'suivi': 5,
        'répondu': 3, 'contacté': 5,
    }
    score += statut_pts.get(contact.get('statut', ''), 0)

    # Structure age (0-20) — established companies more likely to have budget
    dc = contact.get('date_creation', '')
    if dc:
        try:
            created = date.fromisoformat(dc[:10])
            age_years = (date.today() - created).days / 365.25
            if age_years >= 5:
                score += 20
            elif age_years >= 3:
                score += 15
            elif age_years >= 1:
                score += 10
            else:
                score += 5
        except Exception:
            pass

    return score
