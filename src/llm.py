"""LLM-based classification and strategic synthesis (Claude / Anthropic)."""
from __future__ import annotations

import json
import os
import random
import re
from datetime import date
from typing import Any

from anthropic import Anthropic
from pydantic import BaseModel, Field

from src.usage import track_anthropic


class PostClassification(BaseModel):
    index: int
    stage: str = Field(description="TOFU | MOFU | BOFU")
    topic: str
    hook_type: str = Field(description="question | story | stat | bold_claim | list | other")
    angle: str


class ClassificationResponse(BaseModel):
    classifications: list[PostClassification]


class StrategySynthesis(BaseModel):
    positioning: str
    audience: str
    content_pillars: list[str]
    hook_patterns: list[str]
    structural_patterns: list[str]
    cta_strategy: str
    strengths: list[str]
    gaps: list[str]
    actions_to_replicate: list[str]


def _client() -> Anthropic:
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")


_MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _today_fr() -> str:
    """Date du jour en français, ex. « 18 juin 2026 »."""
    t = date.today()
    return f"{t.day} {_MOIS_FR[t.month - 1]} {t.year}"


def _date_directive() -> str:
    """Consigne de fraîcheur temporelle injectée dans les prompts de génération."""
    return (
        f"Nous sommes aujourd'hui le {_today_fr()}. "
        "Raisonne toujours à partir de cette date : saisons, actualités, tendances, "
        "chiffres et exemples doivent être cohérents avec l'année et le mois en cours. "
        "N'évoque jamais une année écoulée comme si elle était présente et n'utilise pas "
        "d'informations périmées ; si une donnée peut avoir changé depuis ta base de "
        "connaissances, reste général plutôt que d'inventer un fait daté."
    )


def _extract_json(text: str) -> dict:
    """Strip Claude's prose / markdown fences and parse JSON."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])
    return json.loads(text)


def _call(system: str, user: str, max_tokens: int = 4096, temperature: float = 0.2) -> dict:
    resp = _client().messages.create(
        model=_model(),
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    usage = getattr(resp, "usage", None)
    if usage:
        track_anthropic(
            _model(),
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )
    text = "".join(block.text for block in resp.content if hasattr(block, "text"))
    return _extract_json(text)


def classify_posts(posts: list[dict]) -> list[dict]:
    """Tag each post with TOFU/MOFU/BOFU + topic + hook type."""
    items = [
        {"index": i, "format": p["format"], "text": p["text"][:1500]}
        for i, p in enumerate(posts)
    ]
    system = (
        "Tu es un analyste contenu B2B. Pour chaque post LinkedIn fourni, classe-le "
        "dans le funnel marketing :\n"
        "- TOFU = awareness, storytelling, opinion, viralité, peu lié à l'offre.\n"
        "- MOFU = expertise, méthodes, frameworks, études de cas, éducation produit.\n"
        "- BOFU = preuve sociale, offre directe, CTA commercial, recrutement client.\n"
        "Réponds UNIQUEMENT avec un objet JSON, sans texte avant ni après, sans balise markdown."
    )
    user = (
        "Classe ces posts. Pour `hook_type` utilise: question, story, stat, "
        "bold_claim, list, other.\n\n"
        "Schéma JSON attendu:\n"
        '{"classifications": [{"index": int, "stage": "TOFU|MOFU|BOFU", '
        '"topic": str, "hook_type": str, "angle": str}, ...]}\n\n'
        "Posts:\n" + json.dumps(items, ensure_ascii=False)
    )
    data = _call(system, user, max_tokens=8192, temperature=0.2)
    parsed = ClassificationResponse(**data)
    return [c.model_dump() for c in parsed.classifications]


def synthesize_strategy(stats: dict, classifications: list[dict], posts: list[dict]) -> dict[str, Any]:
    """Produce strategic synthesis from stats + classifications."""
    sample_posts = [
        {
            "stage": c["stage"],
            "topic": c["topic"],
            "hook_type": c["hook_type"],
            "format": posts[c["index"]]["format"],
            "engagement": posts[c["index"]]["engagement"],
            "likes": posts[c["index"]]["likes"],
            "comments": posts[c["index"]]["comments"],
            "has_cta": posts[c["index"]].get("has_cta", False),
            "url": posts[c["index"]].get("url", ""),
            "first_lines": "\n".join(posts[c["index"]]["text"].splitlines()[:3]),
        }
        for c in classifications
        if c["index"] < len(posts)
    ]

    system = (
        "Tu es un stratège contenu LinkedIn. À partir des stats et des posts classés, "
        "extrais une synthèse stratégique actionnable. Sois concret, factuel, cite des "
        "extraits réels quand utile, évite les généralités. "
        "Règles de fiabilité impératives :\n"
        "- Tout chiffre d'engagement cité doit correspondre EXACTEMENT au champ `engagement` "
        "d'un post fourni ou à une valeur des stats agrégées. N'invente ni n'arrondis aucun chiffre.\n"
        "- `has_cta: true` signifie que les commentaires sont en partie mécaniques "
        "(CTA 'commente X pour recevoir') : tiens-en compte avant de parler d'audience engagée.\n"
        "- Ne tire aucune conclusion sur les formats au-delà de `format_mix_pct` fourni.\n"
        "- Écris pour un lecteur non technique : désigne les accroches par leur libellé français "
        "(« question directe », « histoire/anecdote », « chiffre choc », « affirmation tranchée », "
        "« liste », « résultat chiffré », « contre-pied »), jamais par les codes (bold_claim, stat…). "
        "Pareil pour le funnel : « attraction (TOFU) », « éducation (MOFU) », « conversion (BOFU) ».\n"
        "Réponds UNIQUEMENT avec un objet JSON, sans texte avant ni après, sans balise markdown."
    )
    payload = {
        "stats": {
            "posts_per_week": stats.get("posts_per_week"),
            "weekday_distribution": stats.get("weekday_distribution"),
            "hour_distribution": stats.get("hour_distribution"),
            "format_mix_pct": stats.get("format_mix_pct"),
            "engagement": stats.get("engagement"),
            "length": stats.get("length"),
            "stage_engagement": stats.get("stage_engagement"),
            "hook_engagement": stats.get("hook_engagement"),
            "cta_effect": stats.get("cta_effect"),
        },
        "classifications": sample_posts,
    }
    user = (
        "Données:\n" + json.dumps(payload, ensure_ascii=False) + "\n\n"
        "Schéma JSON attendu (toutes les clés obligatoires):\n"
        "{\n"
        '  "positioning": str,\n'
        '  "audience": str,\n'
        '  "content_pillars": [str, ...],\n'
        '  "hook_patterns": [str, ...],\n'
        '  "structural_patterns": [str, ...],\n'
        '  "cta_strategy": str,\n'
        '  "strengths": [str, ...],\n'
        '  "gaps": [str, ...],\n'
        '  "actions_to_replicate": [str, ...]\n'
        "}"
    )

    data = _call(system, user, max_tokens=4096, temperature=0.4)
    return StrategySynthesis(**data).model_dump()


def _format_user_context(user_context: dict[str, Any] | None) -> str:
    """Render the user's business/editorial profile for LLM prompts."""
    if not user_context:
        return "Aucun contexte client renseigné. Utilise le benchmark influenceurs comme source principale."
    labels = {
        "display_name": "Nom",
        "brand_name": "Marque",
        "industry": "Secteur",
        "business_description": "Activité",
        "location": "Localisation",
        "target_audience": "Audience cible",
        "core_offer": "Offre / expertise",
        "tone": "Ton souhaité",
        "linkedin_objective": "Objectif LinkedIn",
        "topics_to_cover": "Sujets à couvrir",
        "topics_to_avoid": "Sujets à éviter",
        "constraints": "Contraintes",
        "website_url": "Site web",
        "linkedin_url": "Profil LinkedIn",
        "language": "Langue",
        "market": "Marché",
        "extra_context": "Contexte additionnel",
    }
    lines = []
    for key, label in labels.items():
        value = user_context.get(key)
        if value:
            lines.append(f"- {label}: {value}")
    return "\n".join(lines) if lines else "Aucun contexte client exploitable."


EDITORIAL_PROFILE_KEYS = [
    "display_name",
    "brand_name",
    "industry",
    "business_description",
    "location",
    "target_audience",
    "core_offer",
    "tone",
    "linkedin_objective",
    "topics_to_cover",
    "topics_to_avoid",
    "constraints",
    "website_url",
    "linkedin_url",
    "language",
    "market",
    "extra_context",
]


def draft_editorial_profile(
    seed: dict[str, Any],
    existing_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Draft an editorial profile from free text and optional external signals."""
    system = (
        "Tu es un stratège LinkedIn B2B. Tu transformes des informations brutes "
        "sur une personne ou une entreprise en profil éditorial exploitable par une IA de rédaction. "
        "Tu dois être concret, prudent et ne pas inventer de faits précis non fournis. "
        "Quand l'information manque, propose une formulation utile mais générique, ou laisse vide si nécessaire. "
        "Réponds UNIQUEMENT avec un objet JSON valide, sans markdown, sans texte avant/après."
    )
    payload = {
        "sources": seed,
        "profil_existant_a_preserver_si_pertinent": existing_profile or {},
    }
    user = (
        "Crée un brouillon de profil éditorial à partir de ces sources.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + """

Règles :
- Le profil doit aider à écrire des posts LinkedIn crédibles pour cette personne.
- Si une description libre est fournie, elle est la source la plus fiable.
- Si des posts LinkedIn analysés sont fournis, utilise-les pour déduire le ton, l'audience et les sujets récurrents.
- Si un profil LinkedIn lu via Apify est fourni, utilise-le comme contexte métier et éditorial récent.
- Si un résumé de site web est fourni, utilise-le pour clarifier l'offre et le positionnement.
- Ne sauvegarde rien, produis seulement un brouillon.
- Écris en français.

Schéma JSON attendu, toutes les clés présentes avec string (vide si inconnu) :
{
  "profile": {
    "display_name": "",
    "brand_name": "",
    "industry": "",
    "business_description": "",
    "location": "",
    "target_audience": "",
    "core_offer": "",
    "tone": "",
    "linkedin_objective": "",
    "topics_to_cover": "",
    "topics_to_avoid": "",
    "constraints": "",
    "website_url": "",
    "linkedin_url": "",
    "language": "français",
    "market": "",
    "extra_context": ""
  }
}"""
    )
    data = _call(system, user, max_tokens=3000, temperature=0.3)
    profile = data.get("profile", data)
    return {
        key: str(profile.get(key) or "").strip()
        for key in EDITORIAL_PROFILE_KEYS
    }


def generate_ideas(
    top_posts_examples: list[dict],
    benchmark: dict,
    count: int = 5,
    user_context: dict[str, Any] | None = None,
) -> list[dict]:
    """Generate post ideas based on analyzed influencer insights."""
    examples_text = "\n\n".join(
        f"[{e.get('influencer', '?')} | {e.get('engagement', 0)} eng | hook: {e.get('hook_type', 'other')}]\n{e.get('text', '')[:400]}"
        for e in top_posts_examples[:8]
    )
    context_text = _format_user_context(user_context)

    system = (
        "Tu es un stratège contenu LinkedIn. "
        "Tu proposes des idées de posts adaptées au client final en t'appuyant sur son contexte "
        "éditorial et sur des données réelles d'influenceurs analysés. "
        + _date_directive()
        + " Réponds UNIQUEMENT avec un objet JSON valide, sans markdown, sans texte avant/après."
    )
    user = (
        "Contexte client à respecter en priorité :\n"
        + context_text
        + "\n\nBenchmarks issus de l'analyse d'influenceurs LinkedIn :\n"
        + json.dumps(benchmark, ensure_ascii=False, indent=2)
        + "\n\nExemples des posts les plus performants :\n"
        + examples_text
        + f"""

Propose exactement {count} idées de posts LinkedIn originaux et à fort potentiel viral.

Pour chaque idée :
- Adapte l'angle au métier, au marché, à l'audience et à l'objectif LinkedIn du client quand le contexte est disponible
- Identifie un angle unique basé sur les patterns qui marchent dans le corpus
- Propose un hook accrocheur (première ligne du post)
- Explique pourquoi cette idée devrait performer (basé sur les données)
- Indique le type de hook et le niveau du funnel (TOFU/MOFU/BOFU)

Schéma JSON attendu :
{{
  "ideas": [
    {{
      "title": "titre court de l'idée (5-10 mots)",
      "hook": "première ligne du post proposée",
      "hook_type": "stat+contrarian | story+result | question | list | bold_claim",
      "funnel": "TOFU | MOFU | BOFU",
      "angle": "description de l'angle en 1-2 phrases",
      "why_it_works": "explication basée sur les données du corpus",
      "difficulty": "facile | moyen | avancé",
      "estimated_lift": "+X% vs post standard"
    }}
  ]
}}"""
    )
    data = _call(system, user, max_tokens=4096, temperature=0.8)
    return data.get("ideas", [])


def analyze_dashboard_strategy(influencers_data: list[dict], growth_data: list[dict] | None = None) -> str:
    """Generate a deep strategic AI analysis of the dashboard data."""
    system = (
        "Tu es un stratège senior en marketing LinkedIn et personal branding. "
        "Tu analyses des données comparatives de plusieurs influenceurs pour en tirer "
        "des recommandations stratégiques concrètes et actionnables. "
        "Tu dois aller au-delà des chiffres : identifier les stratégies gagnantes, "
        "les corrélations entre formats/hooks/engagement, et recommander des actions précises. "
        + _date_directive()
        + " Réponds en markdown structuré (titres ##, listes, gras). Ne mets PAS de balises ```markdown."
    )

    user = (
        "Voici les données comparatives de plusieurs influenceurs LinkedIn dans la niche IA/automatisation.\n\n"
        "## Données par influenceur\n"
        + json.dumps(influencers_data, ensure_ascii=False, indent=2)
    )

    if growth_data:
        user += (
            "\n\n## Croissance depuis le 25e post\n"
            + json.dumps(growth_data, ensure_ascii=False, indent=2)
        )

    user += """

Produis une analyse stratégique COMPLÈTE et ACTIONNABLE en suivant ce plan :

## 1. Classement stratégique
- Classe les influenceurs par performance RÉELLE (pas juste l'engagement brut — pondère par followers, régularité, qualité des comments)
- Identifie le "best in class" et explique pourquoi

## 2. Stratégies gagnantes identifiées
- Quelles combinaisons format + hook + funnel produisent le plus d'engagement ?
- Quels patterns sont sous-exploités par le groupe mais prouvés par 1-2 influenceurs ?
- Y a-t-il une corrélation entre cadence de publication et engagement ?

## 3. Analyse des corrélations
- CTA vs pas de CTA : quel impact réel ?
- Longueur des posts vs engagement
- Format (carousel/image/texte/document) vs engagement
- Taux d'engagement vs nombre de followers (qui sur-performe son audience ?)

## 4. Recommandations stratégiques
- Pour quelqu'un qui démarre : quelle stratégie adopter ? (avec un plan concret)
- Pour quelqu'un qui a déjà une audience : comment optimiser ?
- 3 "quick wins" à implémenter immédiatement
- 3 stratégies long terme à construire

## 5. Stratégie de contenu recommandée
- Mix funnel optimal (% TOFU/MOFU/BOFU)
- Cadence idéale
- Formats prioritaires
- Types de hooks à privilégier
- Structure de CTA recommandée

"""

    if growth_data:
        user += """## 6. Analyse de croissance
- Quels influenceurs ont la meilleure dynamique de croissance ?
- Corrélation entre stratégie de contenu et croissance
- Prédictions : qui va le plus progresser et pourquoi ?

"""

    resp = _client().messages.create(
        model=_model(),
        max_tokens=8192,
        temperature=0.5,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    usage = getattr(resp, "usage", None)
    if usage:
        track_anthropic(
            _model(),
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )
    return "".join(block.text for block in resp.content if hasattr(block, "text"))


# Rôles éditoriaux disponibles pour la génération de posts (ALE-70).
# Chaque rôle porte sa propre intention, sa structure attendue et son indicateur.
ROLE_SPECS: dict[str, dict[str, str]] = {
    "performance": {
        "label": "Performance",
        "hook_type": "stat+contrarian",
        "indicator": "+40-80% vs post standard",
        "guidance": (
            "Objectif : maximiser l'engagement. Hook fort (chiffre frappant PUIS angle contrarian), "
            "corps en paragraphes courts, framework numéroté (3-7 items avec ↳) puis triple CTA "
            "(💬 commentaire / ♻️ repost / 🔖 enregistrer). C'est le SEUL rôle où la structure "
            "« virale » complète (framework numéroté + triple CTA) est attendue. Cible 1 400-1 800 caractères."
        ),
    },
    "methodologie": {
        "label": "Méthodologie",
        "hook_type": "how-to",
        "indicator": "Valeur perçue / enregistrements",
        "guidance": (
            "Objectif : être réellement utile. Post pédagogique et actionnable qui décompose une méthode, "
            "un process ou un cadre étape par étape, avec des exemples concrets. La clarté prime sur le punch. "
            "Un seul CTA doux (inviter à appliquer ou à enregistrer). PAS de triple CTA."
        ),
    },
    "autorite": {
        "label": "Autorité",
        "hook_type": "expertise",
        "indicator": "Crédibilité / preuve d'expertise",
        "guidance": (
            "Objectif : asseoir l'expertise. Montre une preuve, un retour d'expérience chiffré ou une "
            "prise de position argumentée appuyée sur des faits. Ton assuré et précis. "
            "Framework numéroté NON imposé. PAS de triple CTA (au plus une invitation à échanger)."
        ),
    },
    "story": {
        "label": "Story",
        "hook_type": "story",
        "indicator": "Connexion émotionnelle",
        "guidance": (
            "Objectif : raconter. Part d'une situation vécue, d'un échec ou d'un apprentissage, avec une "
            "vraie narration (situation → tension → bascule → leçon). Ton incarné, première personne. "
            "PAS de framework numéroté. CTA optionnel et discret."
        ),
    },
    "quotidien": {
        "label": "Quotidien",
        "hook_type": "observation",
        "indicator": "Proximité / authenticité",
        "guidance": (
            "Objectif : ancrer dans le réel. Part d'une scène simple, d'une observation terrain ou d'un "
            "moment local. Ton léger et humain. Lien au métier discret, sans forcer la vente. "
            "PAS de structure virale, PAS de framework numéroté, PAS de triple CTA."
        ),
    },
    "opinion": {
        "label": "Opinion",
        "hook_type": "bold_claim",
        "indicator": "Débat / portée",
        "guidance": (
            "Objectif : faire réagir. Prise de position claire et assumée sur un sujet du secteur, "
            "argumentée, qui invite au débat. Une question ouverte en fin pour lancer la conversation. "
            "Framework numéroté NON imposé. Un seul CTA conversationnel."
        ),
    },
    "relationnel": {
        "label": "Relationnel",
        "hook_type": "question",
        "indicator": "Conversation / proximité",
        "guidance": (
            "Objectif : créer du lien. Ton personnel et conversationnel, sentiment de proximité et "
            "d'appartenance (communauté, deuxième maison…). Hook simple et humain (PAS de chiffre choc, "
            "ex. « Hier soir, New York parlait français. »). Lien métier très discret. Une seule question "
            "ouverte en fin. Surtout PAS de structure virale, PAS de framework numéroté, PAS de triple CTA."
        ),
    },
}


def _auto_role_mix() -> list[str]:
    """Mix éditorial par défaut : performance + (méthodo|autorité) + (relationnel|quotidien)."""
    return [
        "performance",
        random.choice(["methodologie", "autorite"]),
        random.choice(["relationnel", "quotidien"]),
    ]


def generate_posts(
    topic: str,
    top_posts_examples: list[dict],
    benchmark: dict,
    user_context: dict[str, Any] | None = None,
    editorial_role: str | None = None,
) -> list[dict]:
    """Generate 3 LinkedIn post variants covering a mix of editorial roles.

    If ``editorial_role`` is provided and known, the 3 variants all use that role.
    Otherwise an automatic mix of complementary roles is produced.
    """
    examples_text = "\n\n".join(
        f"[{e.get('influencer', '?')} | {e.get('engagement', 0)} eng | hook: {e.get('hook_type', 'other')}]\n{e.get('text', '')[:600]}"
        for e in top_posts_examples[:6]
    )
    context_text = _format_user_context(user_context)

    if editorial_role and editorial_role in ROLE_SPECS:
        roles = [editorial_role, editorial_role, editorial_role]
    else:
        roles = _auto_role_mix()

    roles_block = "\n\n".join(
        f'Variant {i + 1} — rôle éditorial "{r}" ({ROLE_SPECS[r]["label"]}) :\n{ROLE_SPECS[r]["guidance"]}'
        for i, r in enumerate(roles)
    )

    system = (
        "Tu es un expert en stratégie LinkedIn. "
        "Tu génères des posts prêts à publier en respectant d'abord le contexte du client, "
        "puis en t'appuyant sur les patterns observés chez les influenceurs analysés. "
        "Tu produis des STRUCTURES VARIÉES : tous les posts ne sont pas des posts viraux optimisés engagement. "
        "Chaque rôle éditorial a sa propre intention et sa propre forme — respecte-les strictement. "
        + _date_directive()
        + " Réponds UNIQUEMENT avec un objet JSON valide, sans markdown, sans texte avant/après."
    )
    user = (
        f'Sujet du post à créer : "{topic}"\n\n'
        "Contexte client à respecter EN PRIORITÉ (prime sur les patterns viraux) :\n"
        + context_text
        + "\n\nBenchmarks issus de l'analyse d'influenceurs LinkedIn :\n"
        + json.dumps(benchmark, ensure_ascii=False, indent=2)
        + "\n\nExemples des posts les plus performants :\n"
        + examples_text
        + "\n\nGénère exactement 3 variants de posts LinkedIn, un par rôle éditorial ci-dessous, "
        "DANS L'ORDRE indiqué :\n\n"
        + roles_block
        + """

Règles communes :
- Le post doit être crédible pour le client : métier, localisation, audience, offre, ton et contraintes priment sur les patterns viraux.
- Si le sujet est une actualité ou une scène locale, relie-la naturellement au contexte client sans forcer la vente.
- N'impose PAS le triple CTA à tous les rôles. N'impose PAS un framework numéroté à tous les rôles. Respecte la consigne propre à chaque rôle.
- Langue : français.
- Ne PAS mettre de balises markdown dans le texte du post.

Schéma JSON attendu (toutes les clés obligatoires) :
{
  "variants": [
    {
      "editorial_role": "le code exact du rôle de ce variant (performance | methodologie | autorite | story | quotidien | opinion | relationnel)",
      "hook_type": str,
      "strategy": "1-2 phrases expliquant l'intention éditoriale de ce variant",
      "predicted_lift": "indicateur adapté au rôle (ex: '+40-80% vs post standard' pour performance, 'Crée du lien / conversation' pour relationnel)",
      "post": "texte complet du post prêt à publier"
    }
  ]
}"""
    )
    data = _call(system, user, max_tokens=6000, temperature=0.7)
    variants = data.get("variants", [])

    # Backfill : si le LLM omet editorial_role (compat), on le déduit de l'ordre demandé.
    for i, v in enumerate(variants):
        if not isinstance(v, dict):
            continue
        role = v.get("editorial_role")
        if not role or role not in ROLE_SPECS:
            role = roles[i] if i < len(roles) else (editorial_role or "performance")
            v["editorial_role"] = role
        spec = ROLE_SPECS.get(role, {})
        if not v.get("hook_type"):
            v["hook_type"] = spec.get("hook_type", "other")
        if not v.get("predicted_lift"):
            v["predicted_lift"] = spec.get("indicator", "")
        if not v.get("strategy"):
            v["strategy"] = ""
    return variants
