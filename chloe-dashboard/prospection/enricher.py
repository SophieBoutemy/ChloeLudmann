import re
import subprocess
import time
import unicodedata
import requests
from urllib.parse import quote_plus, urljoin, urlparse
from bs4 import BeautifulSoup

_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

_SKIP_DIRS = {
    # Registres & données légales
    'pappers.fr', 'societe.com', 'infogreffe.fr', 'verif.com',
    'kompass.com', 'manageo.fr', 'annuaire-entreprises.data.gouv.fr',
    'societe.ninja', 'bodacc.fr', 'portail-ie.fr', 'europages.fr',
    'hoodspot.fr', 'cylex.fr', 'annuaire.', 'laposte.net',
    # Moteurs de recherche & navigateurs
    'google.', 'bing.com', 'duckduckgo.com', 'yahoo.',
    # Réseaux sociaux
    'facebook.com', 'instagram.com', 'linkedin.com', 'twitter.com',
    'youtube.com', 'tiktok.com', 'pinterest.', 'snapchat.com',
    'x.com', 'threads.net', 'discord.com',
    # Encyclopédies & références
    'wikipedia.', 'wikimedia.', 'wikidata.',
    # Médias nationaux & magazines lifestyle
    'lefigaro.fr', 'lemonde.fr', 'leparisien.fr', 'bfmtv.com',
    'cnews.fr', 'rtl.fr', 'europe1.fr', '20minutes.fr', 'actu.fr',
    'journaldesfemmes.fr', 'aufeminin.com', 'parents.fr', 'femme',
    'marmiton.org', 'doctolib.fr', 'allocine.fr', 'senscritique.com',
    'imdb.com', 'marie.fr', 'elle.fr', 'cosmopolitan.fr',
    'ouest-france.fr', 'maville.com', 'francetvinfo.fr',
    # Outils tech non-commerciaux
    'github.com', 'gitlab.com', 'stackoverflow.com', 'julialang.org',
    'microsoft.com', 'cloud.microsoft', 'office.com',
    'apple.com', 'amazon.', 'ebay.', 'etsy.com',
    # Pages jaunes variantes
    'pages.jaunes.fr', 'pagesjaunes.fr',
    # Divers manifestement hors-sujet
    'ameli.fr', 'service-public.fr', 'impots.gouv.fr',
}
_SKIP_EMAIL_DOMAINS = {'example.com', 'test.com', 'domain.com', 'sentry.io', 'wixpress.com'}
_SKIP_EMAIL_PREFIXES = ('noreply', 'no-reply', 'donotreply', 'mailer', 'bounce', 'admin@admin')

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


def _find_website(company_name, nom_dirigeant='', is_ei=False):
    """Search Bing for the company's official website."""
    q = company_name
    if nom_dirigeant:
        q += f' {nom_dirigeant}'
    q += ' site officiel'
    url = f'https://www.bing.com/search?q={quote_plus(q)}&setlang=fr&cc=FR'
    try:
        r = requests.get(url, headers=_HEADERS, timeout=8)
        soup = BeautifulSoup(r.text, 'html.parser')
        for item in soup.select('li.b_algo'):
            cite = item.select_one('cite')
            if not cite:
                continue
            raw = cite.get_text().split('›')[0].strip()
            if not raw:
                continue
            if not raw.startswith('http'):
                raw = 'https://' + raw
            if any(d in raw for d in _SKIP_DIRS):
                continue
            # Always require domain to match company or director name.
            # Better to return nothing than a wrong site.
            if _domain_ok(raw, company_name):
                return raw.rstrip('/')
            if nom_dirigeant and _domain_ok(raw, nom_dirigeant):
                return raw.rstrip('/')
    except Exception:
        pass
    return ''


_MENTIONS_KEYWORDS = ('mention', 'légal', 'legal', 'legale', 'legales', 'cgu', 'cgv')

_STOP_WORDS = {
    # Formes juridiques
    'sarl', 'eurl', 'sas', 'sasu', 'snc', 'sci', 'scop', 'scp',
    'selas', 'selarl', 'eirl', 'sprl',
    # Articles et prépositions courts
    'les', 'des', 'une', 'avec', 'dans', 'pour', 'chez', 'sur', 'sous', 'par',
    # Mots génériques entreprise
    'france', 'french', 'groupe', 'group', 'holding',
    'service', 'services', 'edition', 'editions',
    'solution', 'solutions', 'technology', 'technologies',
    'international', 'consulting', 'conseil', 'management',
    'partners', 'invest', 'investissement', 'distribution',
    # Mots de secteur trop génériques
    'laboratoire', 'laboratoires', 'restaurant', 'maison',
    # Suffixes/parasites fréquents dans les noms INSEE
    'com', 'www',
}


def _asciify(s):
    s = unicodedata.normalize('NFKD', s.lower())
    return re.sub(r'[^a-z0-9]', '', ''.join(c for c in s if not unicodedata.combining(c)))


def _sig_words(company_name):
    """Extract significant words (≥4 chars, not stop words) from a company name."""
    name = re.sub(r'\([^)]*\)', ' ', company_name)
    parts = re.split(r'[\s\-\.\*\/\_&+]+', name)
    return [w for p in parts if len(w := _asciify(p)) >= 4 and w not in _STOP_WORDS]


def _domain_ok(url, name):
    """Return True if the domain plausibly belongs to this name.

    Matching rules (in order):
    1. A sig-word exactly equals a hyphen-segment of the domain (e.g. "artellic" in "artellic-shop")
    2. The domain starts with a sig-word of ≥5 chars (e.g. "confiserie..." starts with "confiserie")
    3. A sig-word of ≥8 chars is a substring AND represents ≥40 % of the domain length

    Never matches by suffix (avoids "femmes" matching "journaldesfemmes").
    """
    words = _sig_words(name)
    if not words:
        return False
    try:
        host = re.sub(r'^www\.', '', urlparse(url).netloc.lower())
        domain_part = _asciify(host.split('.')[0])
        segments = {_asciify(s) for s in host.split('.')[0].split('-') if s}
    except Exception:
        return False
    for w in words:
        if w in segments:
            return True
        if len(w) >= 5 and domain_part.startswith(w):
            return True
        if len(w) >= 8 and w in domain_part and len(w) >= len(domain_part) * 0.40:
            return True
    return False


def _email_from_soup(soup, raw_text):
    for a in soup.find_all('a', href=True):
        if a['href'].startswith('mailto:'):
            cleaned = _clean_email(a['href'][7:])
            if cleaned:
                return cleaned
    for raw in _EMAIL_RE.findall(raw_text):
        cleaned = _clean_email(raw)
        if cleaned:
            return cleaned
    return ''


def _find_mentions_url(soup, base_url):
    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text().lower().strip()
        if any(k in href.lower() or k in text for k in _MENTIONS_KEYWORDS):
            return urljoin(base_url, href)
    return ''


def _extract_email(url):
    if not url:
        return ''
    try:
        r = requests.get(url, headers=_HEADERS, timeout=6, allow_redirects=True)
        return _email_from_soup(BeautifulSoup(r.text, 'html.parser'), r.text)
    except Exception:
        return ''


def enrich_contact(contact):
    is_ei = bool(contact.get('est_ei'))

    if not contact.get('site_web'):
        site = _find_website(contact['nom_entreprise'], contact.get('nom_dirigeant', ''), is_ei=is_ei)
        contact['site_web'] = site
        contact['site_web_statut'] = 'à vérifier' if site else ''
        time.sleep(0.4)

    if contact.get('site_web') and not contact.get('email'):
        base = contact['site_web'].rstrip('/')
        email = ''
        mentions_url = ''
        try:
            r = requests.get(base, headers=_HEADERS, timeout=6, allow_redirects=True)
            soup = BeautifulSoup(r.text, 'html.parser')
            email = _email_from_soup(soup, r.text)
            if not email:
                mentions_url = _find_mentions_url(soup, base)
        except Exception:
            pass
        if not email:
            email = _extract_email(base + '/contact')
        if not email and mentions_url:
            email = _extract_email(mentions_url)
        contact['email'] = email

    contact['email_statut'] = verify_email(contact['email']) if contact.get('email') else ''

    return contact
