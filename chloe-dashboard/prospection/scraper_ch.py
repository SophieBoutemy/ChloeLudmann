"""Swiss company search via the public Zefix REST API."""
import requests
import time

ZEFIX_URL = 'https://www.zefix.ch/ZefixREST/api/v1/firm/search.json'

CANTON_LABELS = {
    'VD': 'Vaud', 'GE': 'Genève', 'NE': 'Neuchâtel', 'FR': 'Fribourg',
    'JU': 'Jura', 'VS': 'Valais', 'BE': 'Berne', 'ZH': 'Zurich',
    'AG': 'Argovie', 'LU': 'Lucerne', 'SG': 'Saint-Gall', 'TI': 'Tessin',
    'BS': 'Bâle-Ville', 'BL': 'Bâle-Campagne', 'SO': 'Soleure',
    'ZG': 'Zoug', 'SZ': 'Schwytz', 'OW': 'Obwald', 'NW': 'Nidwald',
    'GL': 'Glaris', 'UR': 'Uri', 'GR': 'Grisons', 'TG': 'Thurgovie',
    'SH': 'Schaffhouse', 'AR': 'Appenzell Rh.-Ext.', 'AI': 'Appenzell Rh.-Int.',
    'ZH': 'Zurich',
}


def _parse_firm(firm):
    return {
        'siren':           firm.get('uid', ''),
        'nom_entreprise':  (firm.get('name') or '').strip(),
        'nom_dirigeant':   '',
        'naf':             'CH',
        'activite':        '',
        'adresse':         '',
        'code_postal':     '',
        'ville':           (firm.get('legalSeat') or '').title(),
        'departement':     firm.get('canton', ''),
        'date_creation':   '',
        'tranche_effectif': '',
        'est_ei':          False,
        'site_web':        '',
        'email':           '',
    }


def search_companies_ch(keywords, cantons=None, max_results=50):
    """
    keywords: list of search terms (e.g. ['boulangerie', 'pâtisserie'])
    cantons : list of 2-letter codes (e.g. ['VD', 'GE']) or None for all
    """
    seen = set()
    results = []

    canton_list = cantons if cantons else [None]

    for kw in keywords:
        if len(results) >= max_results:
            break
        for canton in canton_list:
            if len(results) >= max_results:
                break
            payload = {
                'name':       kw,
                'activeOnly': True,
                'maxEntries': min(max_results - len(results), 50),
            }
            if canton:
                payload['canton'] = canton
            try:
                r = requests.post(ZEFIX_URL, json=payload, timeout=12)
                r.raise_for_status()
                firms = r.json()
                if not isinstance(firms, list):
                    firms = firms.get('list', [])
                for f in firms:
                    uid = f.get('uid', '')
                    if not uid or uid in seen:
                        continue
                    seen.add(uid)
                    parsed = _parse_firm(f)
                    if parsed['nom_entreprise']:
                        # Inject the searched keyword as the activity label
                        parsed['activite'] = kw.capitalize()
                        results.append(parsed)
                    if len(results) >= max_results:
                        break
            except Exception:
                pass
            time.sleep(0.2)

    return results[:max_results]
