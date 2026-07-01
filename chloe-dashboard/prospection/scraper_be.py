"""Belgian company search via the KBO/BCE public API."""
import re
import requests
import time

KBO_URL = 'https://api.kbo-bce.fgov.be/api/v2/enterprise/search'

PROVINCE_LABELS = {
    'BRU': 'Bruxelles',
    'ANT': 'Anvers',
    'OVL': 'Flandre-Orientale',
    'WVL': 'Flandre-Occidentale',
    'VBR': 'Brabant Flamand',
    'LIM': 'Limbourg',
    'HAI': 'Hainaut',
    'LGE': 'Liège',
    'LUX': 'Luxembourg',
    'NAM': 'Namur',
    'WBR': 'Brabant Wallon',
}


def _parse_company(item, keyword=''):
    address = item.get('address') or {}
    street_name = (address.get('street') or {}).get('name') or address.get('street') or ''
    street_no   = (address.get('street') or {}).get('number') or address.get('number') or ''
    if isinstance(street_name, dict):
        street_name = street_name.get('fr') or street_name.get('nl') or ''
    adresse = (str(street_name) + (' ' + str(street_no) if street_no else '')).strip()

    municipality = address.get('municipality') or {}
    if isinstance(municipality, str):
        ville, zip_code = municipality, ''
    else:
        ville    = municipality.get('name') or municipality.get('fr') or municipality.get('nl') or ''
        if isinstance(ville, dict):
            ville = ville.get('fr') or ville.get('nl') or ''
        zip_code = str(municipality.get('zipCode') or municipality.get('zip') or '')

    nom = (item.get('denomination') or item.get('name') or '').strip()
    if isinstance(nom, dict):
        nom = nom.get('fr') or nom.get('nl') or nom.get('de') or ''

    ent_no = re.sub(r'[^0-9]', '', item.get('enterpriseNumber') or item.get('id') or '')

    return {
        'siren':            ent_no,
        'nom_entreprise':   nom,
        'nom_dirigeant':    '',
        'naf':              'BE',
        'activite':         keyword.capitalize() if keyword else '',
        'adresse':          adresse,
        'code_postal':      zip_code,
        'ville':            str(ville).strip(),
        'departement':      address.get('province', ''),
        'date_creation':    '',
        'tranche_effectif': '',
        'est_ei':           False,
        'site_web':         '',
        'email':            '',
    }


def search_companies_be(keywords, provinces=None, max_results=50, seen=None, offsets=None):
    """
    keywords : list of search terms
    provinces: list of province codes (e.g. ['BRU', 'LGE']) or None for all
    seen     : optional external set of enterprise numbers already processed (mutated in-place)
    offsets  : optional dict {(kw, province): next_start_offset} for pagination across calls
               (mutated in-place; value -1 means that combo is exhausted)
    """
    if seen is None:
        seen = set()
    if offsets is None:
        offsets = {}
    results = []

    province_list = provinces if provinces else [None]

    for kw in keywords:
        if len(results) >= max_results:
            break
        for province in province_list:
            if len(results) >= max_results:
                break
            key = (kw, province)
            if offsets.get(key) == -1:
                continue  # this combo is exhausted
            offset = offsets.get(key, 0)
            while len(results) < max_results:
                params = {
                    'query': kw,
                    'lang': 'fr',
                    'start': offset,
                    'size': 50,
                }
                if province:
                    params['province'] = province
                try:
                    r = requests.get(KBO_URL, params=params, timeout=12)
                    r.raise_for_status()
                    data = r.json()
                    items = (
                        data if isinstance(data, list)
                        else data.get('enterprises', data.get('hits', data.get('results', [])))
                    )
                    if not items:
                        offsets[key] = -1
                        break
                    for item in items:
                        ent_no = re.sub(r'[^0-9]', '',
                                        item.get('enterpriseNumber') or item.get('id') or '')
                        if not ent_no or ent_no in seen:
                            continue
                        if provinces and not province:
                            item_prov = (item.get('address') or {}).get('province', '')
                            if item_prov and item_prov not in provinces:
                                continue
                        seen.add(ent_no)
                        parsed = _parse_company(item, kw)
                        if parsed['nom_entreprise']:
                            results.append(parsed)
                        if len(results) >= max_results:
                            break
                    offset += len(items)
                    offsets[key] = offset
                    if len(items) < 50:
                        offsets[key] = -1  # last page reached
                        break
                except Exception:
                    break
                time.sleep(0.2)

    return results[:max_results]
