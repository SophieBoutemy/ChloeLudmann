import json
import os
import threading
from datetime import datetime

from .scraper import search_companies, NAF_LABELS, TRANCHE_LABELS
from .enricher import enrich_contact
from .storage import init_db, upsert_contact, delete_contacts_empty

_STATUS = os.path.join(os.path.dirname(__file__), 'task_status.json')
_lock = threading.Lock()


def _save(status):
    with _lock:
        with open(_STATUS, 'w', encoding='utf-8') as f:
            json.dump(status, f, ensure_ascii=False)


def get_task_status():
    try:
        with open(_STATUS, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {'running': False, 'progress': 0, 'total': 0,
                'message': 'Aucune recherche lancee', 'finished': None,
                'search_params': None}


def _build_params_label(naf_codes, departements, max_results, tranche_effectifs):
    parts = []
    if naf_codes:
        labels = [NAF_LABELS.get(c, c) for c in naf_codes[:3]]
        if len(naf_codes) > 3:
            labels.append(f'+{len(naf_codes) - 3}')
        parts.append('Secteurs : ' + ', '.join(labels))
    if departements:
        parts.append('Dep. : ' + ', '.join(departements[:5]))
    if tranche_effectifs:
        t_labels = [TRANCHE_LABELS.get(t, t) for t in tranche_effectifs]
        parts.append('Taille : ' + ' '.join(t_labels))
    parts.append(f'Max : {max_results}')
    return ' | '.join(parts)


def _build_params_label_ch(keywords, cantons, max_results):
    parts = []
    if keywords:
        parts.append('Mots-cles : ' + ', '.join(keywords[:3]))
    if cantons:
        parts.append('Cantons : ' + ', '.join(cantons[:5]))
    parts.append(f'Max : {max_results}')
    return 'Suisse | ' + ' | '.join(parts)


def _run(naf_codes, departements, max_results, enrichissement, tranche_effectifs, params_label):
    init_db()
    _save({
        'running': True, 'progress': 0, 'total': max_results,
        'message': "Interrogation de l'API entreprises...",
        'started': datetime.now().strftime('%d/%m/%Y %H:%M'),
        'finished': None,
        'search_params': params_label,
    })
    try:
        seen = set()
        new_count = 0
        updated_count = 0

        while new_count < max_results:
            needed = max_results - new_count
            companies = search_companies(naf_codes, departements or None, needed,
                                         tranche_effectifs, seen)
            if not companies:
                break

            for company in companies:
                if enrichissement:
                    company = enrich_contact(company)
                result = upsert_contact(company)
                has_contact = not enrichissement or company.get('site_web') or company.get('email')
                if result == 'created' and has_contact:
                    new_count += 1
                elif result == 'updated':
                    updated_count += 1
                _save({
                    'running': True, 'progress': new_count, 'total': max_results,
                    'message': f'{new_count} nouveau(x), {updated_count} mis à jour — {company["nom_entreprise"]}',
                    'finished': None,
                    'search_params': params_label,
                })

            if len(companies) < needed:
                break  # API exhausted, no more results available

        removed = delete_contacts_empty()
        parts = [f'{new_count} nouveau(x) contact(s)']
        if updated_count:
            parts.append(f'{updated_count} déjà connu(s) mis à jour')
        if removed:
            parts.append(f'{removed} sans email ni site supprimé(s)')
        final_msg = 'Terminé — ' + ', '.join(parts)
        _save({
            'running': False, 'progress': new_count, 'total': max_results,
            'message': final_msg,
            'finished': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'search_params': params_label,
        })
    except Exception as e:
        _save({
            'running': False, 'progress': 0, 'total': 0,
            'message': f'Erreur : {e}', 'finished': None,
            'search_params': params_label,
        })


def _run_ch(keywords, cantons, max_results, enrichissement, params_label):
    from .scraper_ch import search_companies_ch
    init_db()
    _save({
        'running': True, 'progress': 0, 'total': max_results,
        'message': 'Interrogation de Zefix (Suisse)...',
        'started': datetime.now().strftime('%d/%m/%Y %H:%M'),
        'finished': None,
        'search_params': params_label,
    })
    try:
        seen = set()
        new_count = 0
        updated_count = 0

        while new_count < max_results:
            needed = max_results - new_count
            companies = search_companies_ch(keywords, cantons or None, needed, seen=seen)
            if not companies:
                break

            for company in companies:
                if enrichissement:
                    company = enrich_contact(company)
                result = upsert_contact(company)
                if result == 'created':
                    new_count += 1
                elif result == 'updated':
                    updated_count += 1
                _save({
                    'running': True, 'progress': new_count, 'total': max_results,
                    'message': f'{new_count} nouveau(x), {updated_count} mis à jour — {company["nom_entreprise"]}',
                    'finished': None,
                    'search_params': params_label,
                })

            if len(companies) < needed:
                break  # API exhausted, no more results available

        removed = delete_contacts_empty()
        parts = [f'{new_count} nouveau(x) contact(s) (Suisse)']
        if updated_count:
            parts.append(f'{updated_count} déjà connu(s) mis à jour')
        if removed:
            parts.append(f'{removed} sans email ni site supprimé(s)')
        final_msg = 'Terminé — ' + ', '.join(parts)
        _save({
            'running': False, 'progress': new_count, 'total': max_results,
            'message': final_msg,
            'finished': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'search_params': params_label,
        })
    except Exception as e:
        _save({
            'running': False, 'progress': 0, 'total': 0,
            'message': f'Erreur : {e}', 'finished': None,
            'search_params': params_label,
        })


def start_search(naf_codes, departements, max_results, enrichissement=True,
                 tranche_effectifs=None):
    if get_task_status().get('running'):
        return False
    params_label = _build_params_label(naf_codes, departements, max_results, tranche_effectifs)
    threading.Thread(
        target=_run,
        args=(naf_codes, departements, max_results, enrichissement, tranche_effectifs, params_label),
        daemon=True,
    ).start()
    return True


def start_search_ch(keywords, cantons, max_results, enrichissement=True):
    if get_task_status().get('running'):
        return False
    params_label = _build_params_label_ch(keywords, cantons, max_results)
    threading.Thread(
        target=_run_ch,
        args=(keywords, cantons, max_results, enrichissement, params_label),
        daemon=True,
    ).start()
    return True


def _build_params_label_be(keywords, provinces, max_results):
    parts = []
    if keywords:
        parts.append('Mots-cles : ' + ', '.join(keywords[:3]))
    if provinces:
        from .scraper_be import PROVINCE_LABELS
        labels = [PROVINCE_LABELS.get(p, p) for p in provinces[:5]]
        parts.append('Provinces : ' + ', '.join(labels))
    parts.append(f'Max : {max_results}')
    return 'Belgique | ' + ' | '.join(parts)


def _run_be(keywords, provinces, max_results, enrichissement, params_label):
    from .scraper_be import search_companies_be
    init_db()
    _save({
        'running': True, 'progress': 0, 'total': max_results,
        'message': 'Interrogation de la BCE (Belgique)...',
        'started': datetime.now().strftime('%d/%m/%Y %H:%M'),
        'finished': None,
        'search_params': params_label,
    })
    try:
        seen = set()
        offsets = {}
        new_count = 0
        updated_count = 0

        while new_count < max_results:
            needed = max_results - new_count
            companies = search_companies_be(keywords, provinces or None, needed, seen=seen, offsets=offsets)
            if not companies:
                break

            for company in companies:
                if enrichissement:
                    company = enrich_contact(company)
                result = upsert_contact(company)
                if result == 'created':
                    new_count += 1
                elif result == 'updated':
                    updated_count += 1
                _save({
                    'running': True, 'progress': new_count, 'total': max_results,
                    'message': f'{new_count} nouveau(x), {updated_count} mis à jour — {company["nom_entreprise"]}',
                    'finished': None,
                    'search_params': params_label,
                })

            if len(companies) < needed:
                break  # API exhausted, no more results available

        removed = delete_contacts_empty()
        parts = [f'{new_count} nouveau(x) contact(s) (Belgique)']
        if updated_count:
            parts.append(f'{updated_count} déjà connu(s) mis à jour')
        if removed:
            parts.append(f'{removed} sans email ni site supprimé(s)')
        final_msg = 'Terminé — ' + ', '.join(parts)
        _save({
            'running': False, 'progress': new_count, 'total': max_results,
            'message': final_msg,
            'finished': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'search_params': params_label,
        })
    except Exception as e:
        _save({
            'running': False, 'progress': 0, 'total': 0,
            'message': f'Erreur : {e}', 'finished': None,
            'search_params': params_label,
        })


def start_search_be(keywords, provinces, max_results, enrichissement=True):
    if get_task_status().get('running'):
        return False
    params_label = _build_params_label_be(keywords, provinces, max_results)
    threading.Thread(
        target=_run_be,
        args=(keywords, provinces, max_results, enrichissement, params_label),
        daemon=True,
    ).start()
    return True
