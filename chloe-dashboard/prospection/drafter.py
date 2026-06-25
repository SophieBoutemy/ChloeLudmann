import anthropic
import json
import os

PROFILE_PATH = os.path.join(os.path.dirname(__file__), '..', 'profil_expediteur.json')

_DEFAULT_PROFILE = {
    "prenom": "Sophie",
    "nom": "Boutemy",
    "activite": "Consultante en automatisation et IA pour TPE/PME",
    "proposition_valeur": "J'aide les petites entreprises à automatiser leurs tâches répétitives et à gagner du temps grâce à l'IA.",
    "offre": "",
    "cible": "structures culturelles/associations/team-building",
    "signature": "Sophie Boutemy\nConsultante en automatisation IA\ncontact@sophieboutemy.com",
}

EMAIL_TYPES = {
    "premier_contact": "Premier contact — présentation et proposition de valeur",
    "relance": "Relance — suite à un premier email sans réponse",
    "suivi": "Suivi — après un échange ou une conversation",
}

_TYPE_INSTRUCTIONS = {
    "premier_contact": (
        "- C'est le tout premier email — ne fais pas référence à un échange précédent\n"
        "- Commence par une accroche liée au secteur ou à l'activité du prospect (jamais \"Je me permets de vous contacter\")\n"
        "- Présente l'offre en une seule phrase, avec un bénéfice concret et mesurable\n"
        "- Si des cas d'usage concrets sont renseignés dans le profil, pioche celui qui colle le mieux à ce secteur\n"
        "- Termine par un appel à l'action simple (ex : \"Dispo 15 min cette semaine ?\")"
    ),
    "relance": (
        "- C'est une relance : le premier email n'a pas eu de réponse — le mentionner en une phrase, naturellement\n"
        "- Ne répète pas le même angle que le premier email : trouve un biais différent (question, stat, exemple concret)\n"
        "- Corps très court : 2-3 lignes max, pas de récapitulatif de l'offre entière\n"
        "- Ton détendu, pas insistant\n"
        "- Termine par une question ouverte ou une porte de sortie (ex : \"Toujours pas le bon moment ? Je reviens en septembre.\")"
    ),
    "suivi": (
        "- C'est un suivi après un échange ou une conversation — y faire référence de façon naturelle\n"
        "- L'objectif est de faire avancer vers l'étape suivante (RDV, devis, démo…)\n"
        "- Corps court : 2-4 lignes max\n"
        "- Propose une action concrète et précise (un appel de 20 min, une démo rapide, un devis)\n"
        "- Ton chaleureux, direct"
    ),
}


def load_profile():
    try:
        with open(PROFILE_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return dict(_DEFAULT_PROFILE)


def save_profile(data):
    with open(PROFILE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_draft(contact, email_type="premier_contact"):
    if contact.get('statut') == 'désinscrit':
        raise ValueError("Ce contact est désinscrit et ne peut pas être relancé.")

    profile = load_profile()
    type_label = EMAIL_TYPES.get(email_type, "Premier contact")
    type_instructions = _TYPE_INSTRUCTIONS.get(email_type, _TYPE_INSTRUCTIONS["premier_contact"])

    parts = [f"- Entreprise : {contact.get('nom_entreprise', '')}"]
    if contact.get('nom_dirigeant'):
        parts.append(f"- Dirigeant : {contact['nom_dirigeant']}")
    parts.append(f"- Secteur : {contact.get('activite', '')}")
    if contact.get('ville'):
        parts.append(f"- Ville : {contact['ville']}")
    company_info = '\n'.join(parts)

    offre_block = ''
    if profile.get('offre', '').strip():
        offre_block = f"Cas d'usage concrets / exemples de livrables : {profile['offre'].strip()}\n"

    system_prompt = (
        f"Tu es {profile.get('prenom', 'Sophie')} {profile.get('nom', 'Boutemy')}, "
        f"{profile.get('activite', '')}.\n"
        f"Ta proposition de valeur : {profile.get('proposition_valeur', '')}\n"
        f"{offre_block}"
        f"Tu rédiges des emails de prospection B2B en français pour {profile.get('cible', 'TPE/PME')}.\n\n"
        "Style à respecter impérativement :\n"
        "Phrases courtes.\n"
        "INTERDICTION ABSOLUE des caractères — et - utilisés pour juxtaposer ou énumérer des idées dans une phrase (tiret cadratin ou tiret simple). "
        "Exemple à NE JAMAIS produire : 'qui gèrent ça automatiquement — relances email, suivi des commandes, génération de documents.' "
        "Écris plutôt : 'qui gèrent ça automatiquement. Relances email, suivi des commandes, génération de documents.' "
        "Utilise des points pour séparer les idées, jamais un tiret.\n"
        "Rien qui sonne généré par IA : pas d'énumérations avec tirets dans le corps, pas de formules trop lissées, pas de tournures marketing.\n"
        "Écris comme si tu écrivais vraiment à quelqu'un : style direct, oral, humain.\n"
        "Salutation : si le nom du dirigeant est disponible et contient un prénom exploitable (pas un sigle ni une raison sociale), commence par 'Bonjour [prénom]'. Sinon, utilise une formule neutre adaptée — jamais 'Salut' générique.\n"
        "Ton sobre : pas de tournures emphatiques, pas d'enthousiasme exagéré, pas de formules grandiloquentes dans l'accroche ni ailleurs. Rester factuel, direct. C'est un signe reconnaissable de texte généré par IA — à éviter absolument.\n"
        "Vouvoyer systématiquement le prospect dans tous les types de message (premier contact, relance, suivi). Jamais de tutoiement."
    )

    user_prompt = (
        f"Rédige un email de type \"{type_label}\" pour ce prospect :\n"
        f"{company_info}\n\n"
        f"Consignes spécifiques à ce type :\n{type_instructions}\n\n"
        "Consignes générales :\n"
        "- Pas de liste à puces dans l'email\n"
        "- Pas de formules de politesse formelles (pas de \"Madame, Monsieur\")\n"
        f"- Signature exacte à utiliser :\n{profile.get('signature', '')}\n\n"
        "Réponds UNIQUEMENT en JSON valide, sans markdown, sans explication :\n"
        "{\"subject\": \"Objet de l'email\", \"body\": \"Corps complet avec signature\"}"
    )

    client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY', ''))
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith('```'):
        lines = raw.split('\n')
        inner = lines[1:-1] if lines[-1].strip() == '```' else lines[1:]
        raw = '\n'.join(inner).strip()

    return json.loads(raw)
