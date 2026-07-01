import re
import os
import subprocess
import time
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup

_SOCIETEINFO_KEY = os.getenv('SOCIETEINFO_API_KEY_CHLOE', '')

_SKIP_EMAIL_DOMAINS = {'example.com', 'test.com', 'domain.com', 'sentry.io', 'wixpress.com'}
_SKIP_EMAIL_PREFIXES = ('noreply', 'no-reply', 'donotreply', 'mailer', 'bounce', 'admin@admin',
                       'mon.adresse', 'exemple', 'test', 'demo')

_GENERIC_PREFIXES = frozenset({
    'contact', 'info', 'hello', 'bonjour', 'accueil', 'welcome', 'mail',
    'email', 'support', 'aide', 'help', 'service', 'services',
    'commercial', 'vente', 'ventes', 'sales', 'direction', 'bureau',
    'secretariat', 'administration', 'admin', 'comptabilite', 'compta',
    'facture', 'factures', 'invoice', 'rh', 'recrutement', 'emploi',
    'communication', 'presse', 'media', 'marketing', 'pro',
    'reservation', 'booking', 'rdv', 'agenda', 'newsletter', 'news',
    'webmaster', 'postmaster', 'hostmaster', 'root', 'office', 'general',
    'infos', 'equipe', 'team',
})


def classify_email(email):
    """Return 'nominatif', 'generique', or 'inconnu'."""
    prefix = email.split('@')[0].lower()
    prefix_clean = re.sub(r'\d+$', '', prefix)
    if prefix_clean in _GENERIC_PREFIXES:
        return 'generique'
    for sep in ('.', '-', '_'):
        if sep in prefix_clean:
            parts = [p for p in prefix_clean.split(sep) if p]
            if len(parts) >= 2 and all(len(p) >= 1 and p.isalpha() for p in parts):
                return 'nominatif'
    return 'inconnu'


_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0'
    ),
    'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


def _clean_email(raw):
    email = raw.lower().strip().split('?')[0]
    if '@' not in email:
        return None
    prefix, domain = email.rsplit('@', 1)
    if domain in _SKIP_EMAIL_DOMAINS:
        return None
    if any(prefix.startswith(p) for p in _SKIP_EMAIL_PREFIXES):
        return None
    if re.search(r'\.(png|jpg|gif|css|js|svg|ico|woff)$', domain):
        return None
    if any(s in domain for s in ('sentry.io', 'ingest.')):
        return None
    if len(prefix) < 2 or len(domain) < 4:
        return None
    return email


def _has_mx(domain):
    """True = MX exists, False = no MX, None = lookup failed."""
    try:
        r = subprocess.run(
            ['dig', '+short', 'MX', domain],
            capture_output=True, text=True, timeout=5,
        )
        return bool(r.stdout.strip())
    except Exception:
        try:
            r = subprocess.run(
                ['host', '-t', 'MX', domain],
                capture_output=True, text=True, timeout=5,
            )
            return 'mail is handled' in r.stdout
        except Exception:
            return None


def verify_email(email):
    """Returns 'vérifié', 'à risque', or 'invalide'."""
    if not email or not _EMAIL_RE.fullmatch(email):
        return 'invalide'
    domain = email.rsplit('@', 1)[1]
    mx = _has_mx(domain)
    if mx is False:
        return 'à risque'
    return 'vérifié'  # True or None → accepted by default


_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')


def _find_website(siren):
    """Fetch official website and email from Societeinfo API (lookup by SIREN)."""
    if not siren or not _SOCIETEINFO_KEY:
        return '', ''
    try:
        r = requests.get(
            'https://societeinfo.com/app/rest/api/v2/company.json',
            params={'registration_number': siren, 'key': _SOCIETEINFO_KEY},
            timeout=8,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get('success'):
                result = data['result']
                url = result.get('web_infos', {}).get('website_url', '')
                email = result.get('contacts', {}).get('email', '')
                return url.rstrip('/') if url else '', email or ''
    except Exception:
        pass
    return '', ''


_MENTIONS_KEYWORDS = ('mention', 'légal', 'legal', 'legale', 'legales', 'cgu', 'cgv')


def _collect_emails_from_soup(soup, raw_text):
    """Return all valid emails from a page, mailto links first."""
    seen, result = set(), []
    for a in soup.find_all('a', href=True):
        if a['href'].startswith('mailto:'):
            e = _clean_email(a['href'][7:])
            if e and e not in seen:
                seen.add(e)
                result.append(e)
    for raw in _EMAIL_RE.findall(raw_text):
        e = _clean_email(raw)
        if e and e not in seen:
            seen.add(e)
            result.append(e)
    return result


def _best_email(candidates):
    """Return (email, email_type) preferring nominatif > generique > inconnu."""
    for typ in ('nominatif', 'generique', 'inconnu'):
        for e in candidates:
            if classify_email(e) == typ:
                return e, typ
    return '', ''


def _email_from_soup(soup, raw_text):
    return _best_email(_collect_emails_from_soup(soup, raw_text))[0]


def _find_mentions_url(soup, base_url):
    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text().lower().strip()
        if any(k in href.lower() or k in text for k in _MENTIONS_KEYWORDS):
            return urljoin(base_url, href)
    return ''


def _collect_emails_from_url(url):
    """Fetch a URL and return all valid emails found."""
    if not url:
        return []
    try:
        r = requests.get(url, headers=_HEADERS, timeout=6, allow_redirects=True)
        return _collect_emails_from_soup(BeautifulSoup(r.text, 'html.parser'), r.text)
    except Exception:
        return []


def _extract_email(url):
    return _best_email(_collect_emails_from_url(url))[0]


def enrich_contact(contact):
    is_ei = bool(contact.get('est_ei'))

    if not contact.get('site_web'):
        site, api_email = _find_website(contact.get('siren', ''))
        contact['site_web'] = site
        contact['site_web_statut'] = 'à vérifier' if site else ''
        if api_email and not contact.get('email'):
            contact['email'] = api_email
        time.sleep(0.4)

    if contact.get('site_web') and not contact.get('email'):
        base = contact['site_web'].rstrip('/')
        all_emails = []
        mentions_url = ''
        try:
            r = requests.get(base, headers=_HEADERS, timeout=6, allow_redirects=True)
            soup = BeautifulSoup(r.text, 'html.parser')
            all_emails = _collect_emails_from_soup(soup, r.text)
            if not all_emails:
                mentions_url = _find_mentions_url(soup, base)
        except Exception:
            pass
        if not any(classify_email(e) == 'nominatif' for e in all_emails):
            all_emails += _collect_emails_from_url(base + '/contact')
        if mentions_url and not any(classify_email(e) == 'nominatif' for e in all_emails):
            all_emails += _collect_emails_from_url(mentions_url)
        seen_set = set()
        deduped = [e for e in all_emails if not (e in seen_set or seen_set.add(e))]
        email, email_type = _best_email(deduped)
        contact['email'] = email
        contact['email_type'] = email_type

    contact['email_statut'] = verify_email(contact['email']) if contact.get('email') else ''
    if 'email_type' not in contact:
        contact['email_type'] = classify_email(contact['email']) if contact.get('email') else ''

    return contact
