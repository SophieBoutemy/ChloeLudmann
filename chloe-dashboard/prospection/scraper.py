import math
import time
import requests

API_URL = 'https://recherche-entreprises.api.gouv.fr/search'

NAF_LABELS = {
    # Artisanat & BTP
    '43.22A': 'Plomberie / installation eau et gaz',
    '43.21A': 'Installation électrique',
    '43.34Z': 'Travaux de peinture et vitrerie',
    '43.32A': 'Menuiserie bois et PVC',
    '43.39Z': 'Autres travaux de finition',
    # Commerce & vente
    '47.91A': 'Vente à distance sur catalogue général',
    '47.91B': 'Vente à distance sur catalogue spécialisé',
    '47.71Z': "Commerce de détail d'habillement",
    '47.19B': 'Autres commerces de détail en magasin non spécialisé',
    # Services aux entreprises
    '70.22Z': 'Conseil pour les affaires et autres conseils de gestion',
    '62.01Z': 'Programmation informatique',
    '63.11Z': 'Traitement de données, hébergement',
    '73.11Z': 'Agences de publicité',
    '74.30Z': 'Traduction et interprétation',
    '82.99Z': 'Autres activités de soutien aux entreprises',
    # Santé & bien-être
    '86.90F': 'Activités de santé humaine non classées',
    '96.04Z': 'Entretien corporel',
    '85.51Z': 'Enseignement de disciplines sportives et de loisirs',
    # Enseignement & formation
    '85.59A': "Formation continue d'adultes",
    '85.52Z': 'Enseignement culturel',
    '85.59B': 'Autres enseignements',
    # Culture, art & création
    '74.20Z': 'Activités photographiques',
    '90.03A': 'Création artistique — arts plastiques',
    '90.03B': 'Autre création artistique',
    '74.10Z': 'Activités spécialisées de design',
    # Hôtellerie, restauration & événementiel
    '56.10C': 'Restauration de type rapide',
    '56.21Z': 'Services des traiteurs',
    '82.30Z': 'Organisation de salons professionnels et congrès',
    # Professions juridiques, comptables & financières
    '69.10Z': 'Activités juridiques',
    '69.20Z': 'Activités comptables',
    '66.19B': 'Autres activités auxiliaires de services financiers',
    # Immobilier
    '68.31Z': 'Agences immobilières',
    '68.32A': "Administration d'immeubles",
    # Transport & services à la personne
    '49.32Z': 'Transports de voyageurs par taxis / VTC',
    '49.42Z': 'Services de déménagement',
    '88.10A': 'Aide à domicile',
}

# INSEE tranche codes (used as API filter)
TRANCHE_LABELS = {
    'NN': '0 salarié (non employeur)',
    '00': '0 salarié',
    '01': '1-2 salariés',
    '02': '3-5 salariés',
    '03': '6-9 salariés',
    '11': '10-19 salariés',
    '12': '20-49 salariés',
    '21': '50-99 salariés',
    '22': '100-199 salariés',
}


def _parse(hit, naf_code):
    siege = hit.get('siege', {}) or {}
    dirigeants = hit.get('dirigeants', []) or []
    nom_dirigeant = ''
    if dirigeants:
        d = dirigeants[0]
        prenom = (d.get('prenoms') or '').split()[0] if d.get('prenoms') else ''
        nom = d.get('nom', '')
        nom_dirigeant = f'{prenom} {nom}'.strip() if prenom or nom else ''

    return {
        'siren':            hit.get('siren', ''),
        'nom_entreprise':   (hit.get('nom_complet') or '').strip(),
        'nom_dirigeant':    nom_dirigeant,
        'naf':              naf_code,
        'activite':         NAF_LABELS.get(naf_code, naf_code),
        'adresse':          (siege.get('adresse') or '').strip(),
        'code_postal':      siege.get('code_postal', ''),
        'ville':            (siege.get('libelle_commune') or '').title(),
        'departement':      siege.get('departement', ''),
        'date_creation':    siege.get('date_debut_activite', ''),
        'tranche_effectif': (siege.get('tranche_effectif_salarie') or '').strip(),
        'est_ei':           (hit.get('complements', {}) or {}).get('est_entrepreneur_individuel', False),
        'site_web':         '',
        'email':            '',
    }


def _fetch_naf(naf, departements, quota, seen, tranches=None):
    """Fetch up to `quota` unique independent companies for one NAF code."""
    collected = []
    depts = departements if departements else [None]
    tranche_list = tranches if tranches else [None]

    for dept in depts:
        if len(collected) >= quota:
            break
        for tranche in tranche_list:
            if len(collected) >= quota:
                break
            page = 1
            while len(collected) < quota:
                params = {
                    'activite_principale': naf,
                    'etat_administratif':  'A',
                    'per_page':            25,
                    'page':                page,
                }
                if dept:
                    params['departement'] = dept
                if tranche:
                    params['tranche_effectif_salarie'] = tranche
                try:
                    r = requests.get(API_URL, params=params, timeout=15)
                    r.raise_for_status()
                    data = r.json()
                except Exception:
                    break

                hits = data.get('results', [])
                if not hits:
                    break

                for hit in hits:
                    siren = hit.get('siren', '')
                    if not siren or siren in seen:
                        continue
                    # Skip franchises and chains
                    complements = hit.get('complements', {}) or {}
                    if complements.get('est_franchisee'):
                        continue
                    if (hit.get('nombre_etablissements_ouverts') or 0) > 5:
                        continue
                    seen.add(siren)
                    company = _parse(hit, naf)
                    if company['nom_entreprise']:
                        collected.append(company)
                    if len(collected) >= quota:
                        break

                total = data.get('total_results', 0)
                if page * 25 >= total:
                    break
                page += 1
                time.sleep(0.3)

    return collected


def search_companies(naf_codes, departements=None, max_results=50, tranche_effectifs=None, seen=None):
    """
    tranche_effectifs: list of INSEE tranche codes, or None for all sizes.
    seen: optional set of already-fetched SIRENs (mutated in place for incremental calls).
    """
    if not naf_codes:
        return []
    if seen is None:
        seen = set()
    per_naf = math.ceil(max_results / len(naf_codes))
    results = []

    for naf in naf_codes:
        results.extend(_fetch_naf(naf, departements, per_naf, seen, tranche_effectifs))

    return results[:max_results]
