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


# Les modèles récents (Opus 4.7/4.8, Fable 5, Mythos 5) ont supprimé les
# paramètres d'échantillonnage : envoyer `temperature` (ou top_p/top_k) renvoie
# une erreur 400. On ne le transmet donc qu'aux modèles plus anciens.
_NO_SAMPLING_TAGS = ("opus-4-7", "opus-4-8", "fable", "mythos")


def _accepts_temperature(model: str) -> bool:
    return not any(tag in model for tag in _NO_SAMPLING_TAGS)


_MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _today_fr() -> str:
    """Date du jour en français, ex. « 18 juin 2026 »."""
    t = date.today()
    return f"{t.day} {_MOIS_FR[t.month - 1]} {t.year}"


def _web_search_enabled() -> bool:
    """Recherche web activée via la variable d'env ENABLE_WEB_SEARCH (coût Apify-like)."""
    return os.environ.get("ENABLE_WEB_SEARCH", "").strip().lower() in ("1", "true", "yes", "on")


def _web_search_tools(enabled: bool | None = None) -> list[dict] | None:
    """Outil serveur de recherche web pour la génération, plafonné pour maîtriser le coût.

    Si `enabled` est fourni, il prime sur la variable d'env ENABLE_WEB_SEARCH.
    Renvoie None si désactivé."""
    active = enabled if enabled is not None else _web_search_enabled()
    if not active:
        return None
    try:
        max_uses = int(os.environ.get("WEB_SEARCH_MAX_USES", "3"))
    except ValueError:
        max_uses = 3
    return [{"type": "web_search_20260209", "name": "web_search", "max_uses": max(1, max_uses)}]


def _date_directive() -> str:
    """Consigne de fraîcheur temporelle injectée dans les prompts de génération."""
    base = (
        f"Nous sommes aujourd'hui le {_today_fr()}. "
        "Raisonne toujours à partir de cette date : saisons, actualités, tendances, "
        "chiffres et exemples doivent être cohérents avec l'année et le mois en cours. "
        "N'évoque jamais une année écoulée comme si elle était présente et n'utilise pas "
        "d'informations périmées ; si une donnée peut avoir changé depuis ta base de "
        "connaissances, reste général plutôt que d'inventer un fait daté."
    )
    if _web_search_enabled():
        base += (
            " Tu disposes d'un outil de recherche web : utilise-le pour vérifier une "
            "actualité, une tendance ou un chiffre récent avant de l'affirmer, plutôt "
            "que de te fier uniquement à ta mémoire."
        )
    return base


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


def _track(resp) -> None:
    usage = getattr(resp, "usage", None)
    if usage:
        track_anthropic(
            _model(),
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )


def _call(
    system: str,
    user: str,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    tools: list[dict] | None = None,
) -> dict:
    client = _client()
    messages: list[dict] = [{"role": "user", "content": user}]
    kwargs: dict[str, Any] = dict(
        model=_model(),
        max_tokens=max_tokens,
        system=system,
    )
    if _accepts_temperature(kwargs["model"]):
        kwargs["temperature"] = temperature
    if tools:
        kwargs["tools"] = tools

    resp = client.messages.create(messages=messages, **kwargs)
    _track(resp)
    # Les outils serveur (recherche web) mettent le run en pause quand ils
    # atteignent la limite d'itérations : on relance jusqu'à la réponse finale.
    guard = 0
    while getattr(resp, "stop_reason", None) == "pause_turn" and guard < 5:
        guard += 1
        messages.append({"role": "assistant", "content": resp.content})
        resp = client.messages.create(messages=messages, **kwargs)
        _track(resp)

    text = "".join(
        block.text for block in resp.content if getattr(block, "type", None) == "text"
    )
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
    web_search: bool = False,
    seed_topic: str | None = None,
) -> list[dict]:
    """Generate post ideas based on analyzed influencer insights.

    When `seed_topic` is provided (e.g. an idea the client dropped in their
    reservoir), it becomes the mandatory theme to develop in priority — the
    benchmark/corpus is then used to enrich it rather than to pick the angle.
    """
    examples_text = "\n\n".join(
        f"[{e.get('influencer', '?')} | {e.get('engagement', 0)} eng | hook: {e.get('hook_type', 'other')}]\n{e.get('text', '')[:400]}"
        for e in top_posts_examples[:8]
    )
    context_text = _format_user_context(user_context)
    seed_directive = (
        f"\n\nIdée imposée par le client à développer en priorité aujourd'hui : « {seed_topic} ».\n"
        "Construis les idées autour de ce thème en l'enrichissant avec les patterns du corpus.\n"
        if seed_topic
        else ""
    )

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
        + seed_directive
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
    data = _call(system, user, max_tokens=4096, temperature=0.8, tools=_web_search_tools(web_search or None))
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

    client = _client()
    messages: list[dict] = [{"role": "user", "content": user}]
    kwargs: dict[str, Any] = dict(model=_model(), max_tokens=8192, system=system)
    if _accepts_temperature(kwargs["model"]):
        kwargs["temperature"] = 0.5
    tools = _web_search_tools()
    if tools:
        kwargs["tools"] = tools

    resp = client.messages.create(messages=messages, **kwargs)
    _track(resp)
    guard = 0
    while getattr(resp, "stop_reason", None) == "pause_turn" and guard < 5:
        guard += 1
        messages.append({"role": "assistant", "content": resp.content})
        resp = client.messages.create(messages=messages, **kwargs)
        _track(resp)
    return "".join(
        block.text for block in resp.content if getattr(block, "type", None) == "text"
    )


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
    """Mix éditorial par défaut : performance + méthodo/autorité + relationnel/quotidien + opinion + story."""
    return [
        "performance",
        random.choice(["methodologie", "autorite"]),
        random.choice(["relationnel", "quotidien"]),
        random.choice(["opinion", "story"]),
        random.choice(["methodologie", "autorite", "relationnel", "quotidien"]),
    ]


def generate_posts(
    topic: str,
    top_posts_examples: list[dict],
    benchmark: dict,
    user_context: dict[str, Any] | None = None,
    editorial_role: str | None = None,
    web_search: bool = False,
    count: int = 1,
) -> list[dict]:
    """Generate LinkedIn post variants (default 1) covering editorial roles.

    If ``editorial_role`` is provided and known, all variants use that role.
    Otherwise an automatic mix of complementary roles is produced.
    """
    examples_text = "\n\n".join(
        f"[{e.get('influencer', '?')} | {e.get('engagement', 0)} eng | hook: {e.get('hook_type', 'other')}]\n{e.get('text', '')[:600]}"
        for e in top_posts_examples[:6]
    )
    context_text = _format_user_context(user_context)

    count = max(1, min(count, 5))
    if editorial_role and editorial_role in ROLE_SPECS:
        roles = [editorial_role] * count
    else:
        all_roles = _auto_role_mix()
        roles = all_roles[:count]

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
        + f"\n\nGénère exactement {count} variant{'s' if count > 1 else ''} de post{'s' if count > 1 else ''} LinkedIn, un par rôle éditorial ci-dessous, "
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
    data = _call(system, user, max_tokens=6000, temperature=0.7, tools=_web_search_tools(web_search or None))
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


# ── Assistant conversationnel (ALE-79) ──

def _chat_system_prompt(
    top_posts_examples: list[dict],
    benchmark: dict,
    user_context: dict[str, Any] | None = None,
) -> str:
    examples = [
        {
            "influencer": e.get("influencer"),
            "engagement": e.get("engagement", 0),
            "hook_type": e.get("hook_type", "other"),
            "format": e.get("format"),
            "text": (e.get("text") or "")[:900],
        }
        for e in top_posts_examples[:8]
    ]
    return (
        "Tu es l'assistant conversationnel de Strategy Decoder pour la génération "
        "et l'amélioration de posts LinkedIn B2B.\n\n"
        "Mission : aider l'utilisateur à itérer comme avec un copilote éditorial : "
        "trouver des idées, challenger les angles, rédiger, réécrire, améliorer les hooks, "
        "adapter le ton et transformer des brouillons en posts prêts à publier.\n\n"
        "Contraintes V1 : tu n'as aucun outil externe. Tu ne peux pas lancer une analyse, "
        "publier sur LinkedIn, ni lire de données en dehors du contexte fourni ci-dessous. "
        "Si l'utilisateur demande une action externe, explique brièvement la limite et propose "
        "le meilleur livrable textuel possible.\n\n"
        "Priorité de contexte :\n"
        "1. Respecte d'abord le profil éditorial du client.\n"
        "2. Utilise ensuite les benchmarks et exemples de posts performants comme inspiration, "
        "sans copier les textes.\n"
        "3. Garde les réponses concrètes, en français, avec du markdown lisible quand utile.\n\n"
        "Profil éditorial client :\n"
        f"{_format_user_context(user_context)}\n\n"
        "Benchmarks influenceurs disponibles :\n"
        f"{json.dumps(benchmark, ensure_ascii=False, indent=2)}\n\n"
        "Exemples de posts performants :\n"
        f"{json.dumps(examples, ensure_ascii=False, indent=2)}"
    )


def chat_stream(
    messages: list[dict[str, str]],
    top_posts_examples: list[dict],
    benchmark: dict,
    user_context: dict[str, Any] | None = None,
):
    """Stream a conversational assistant response as text deltas."""
    anthropic_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in messages[-24:]
        if m.get("role") in {"user", "assistant"} and (m.get("content") or "").strip()
    ]
    system = _chat_system_prompt(top_posts_examples, benchmark, user_context=user_context)
    stream_kwargs: dict[str, Any] = dict(
        model=_model(),
        max_tokens=6000,
        system=system,
        messages=anthropic_messages,
    )
    if _accepts_temperature(stream_kwargs["model"]):
        stream_kwargs["temperature"] = 0.7
    with _client().messages.stream(**stream_kwargs) as stream:
        for text in stream.text_stream:
            yield text
        final_message = stream.get_final_message()
    usage = getattr(final_message, "usage", None)
    if usage:
        track_anthropic(
            _model(),
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )


# ── Instagram LLM functions (ALE-93) ─────────────────────────────────────────


class ReelClassification(BaseModel):
    index: int
    stage: str = Field(description="Awareness | Engagement | Conversion")
    hook_type: str = Field(description="question | story | stat | bold_claim | list | contrarian | other")
    topic: str
    has_hook_parle: bool = Field(description="True if transcript has a clear spoken hook in the first 3 seconds")


class ReelClassificationResponse(BaseModel):
    classifications: list[ReelClassification]


def classify_reels_instagram(posts: list[dict]) -> list[dict]:
    """Classify Instagram Reels by funnel stage (Awareness/Engagement/Conversion) and hook type.

    Uses both caption text and transcript (first 200 chars) for classification.
    Handles up to 25 posts like classify_posts for LinkedIn.
    """
    items = []
    for i, p in enumerate(posts[:25]):
        transcript_preview = (p.get("transcript") or "")[:200].strip()
        items.append({
            "index": i,
            "format": p.get("format", "reel"),
            "caption": p.get("text", "")[:800],
            "transcript_preview": transcript_preview,
            "views": p.get("views", 0),
            "likes": p.get("likes", 0),
            "comments": p.get("comments", 0),
        })

    system = (
        "Tu analyses des Reels Instagram. Classe chaque reel dans le funnel :\n"
        "- Awareness : contenu large, divertissement, stories, opinions (attirer de nouvelles personnes)\n"
        "- Engagement : tutoriels, éducation, méthodes, cas concrets (créer une relation)\n"
        "- Conversion : preuves, offres, témoignages, appels à l'action directs (inciter à agir)\n\n"
        "Et le type d'accroche (première ligne caption + 3 premières secondes du transcript si disponible):\n"
        "question, story, stat, bold_claim, list, contrarian, other\n\n"
        "Réponds UNIQUEMENT avec un objet JSON, sans texte avant ni après, sans balise markdown."
    )
    user = (
        "Classe ces Reels Instagram. Pour chaque reel, donne :\n"
        "index (0-based), stage (Awareness|Engagement|Conversion), hook_type, topic (sujet en 3-5 mots), "
        "has_hook_parle (bool — true si le transcript a une accroche verbale claire dans les 3 premières secondes).\n\n"
        "Schéma JSON attendu:\n"
        '{"classifications": [{"index": int, "stage": "Awareness|Engagement|Conversion", '
        '"hook_type": str, "topic": str, "has_hook_parle": bool}, ...]}\n\n'
        "Reels:\n" + json.dumps(items, ensure_ascii=False)
    )
    data = _call(system, user, max_tokens=8192, temperature=0.2)
    parsed = ReelClassificationResponse(**data)
    return [c.model_dump() for c in parsed.classifications]


def synthesize_ig_strategy(stats: dict, classifications: list[dict], posts_enriched: list[dict]) -> dict[str, Any]:
    """Generate Instagram-specific strategic synthesis.

    Uses the same StrategySynthesis schema as synthesize_strategy but with
    an Instagram-focused prompt (retention, visual/spoken hooks, duration, sounds, hashtags).
    """
    sample_posts = [
        {
            "stage": c["stage"],
            "topic": c["topic"],
            "hook_type": c["hook_type"],
            "has_hook_parle": c.get("has_hook_parle", False),
            "format": posts_enriched[c["index"]].get("format") if c["index"] < len(posts_enriched) else "reel",
            "views": posts_enriched[c["index"]].get("views", 0) if c["index"] < len(posts_enriched) else 0,
            "engagement": posts_enriched[c["index"]].get("engagement", 0) if c["index"] < len(posts_enriched) else 0,
            "video_duration_s": posts_enriched[c["index"]].get("video_duration_s") if c["index"] < len(posts_enriched) else None,
            "has_cta": posts_enriched[c["index"]].get("has_cta", False) if c["index"] < len(posts_enriched) else False,
            "cta_keyword": posts_enriched[c["index"]].get("cta_keyword") if c["index"] < len(posts_enriched) else None,
            "first_lines": "\n".join((posts_enriched[c["index"]].get("text") or "").splitlines()[:2]) if c["index"] < len(posts_enriched) else "",
        }
        for c in classifications
        if c["index"] < len(posts_enriched)
    ]

    system = (
        "Tu es un stratège contenu Instagram spécialisé Reels. À partir des stats et des reels classés, "
        "extrais une synthèse stratégique actionnable spécifique à Instagram. "
        "Analyse notamment : la rétention (durée optimale des reels), les accroches visuelles et parlées, "
        "les sons/musiques, les hashtags, les CTAs (lien bio, DM, tag, save, follow). "
        "Sois concret, factuel, cite des données réelles quand utile, évite les généralités. "
        "Réponds UNIQUEMENT avec un objet JSON, sans texte avant ni après, sans balise markdown."
    )
    payload = {
        "stats": {
            "posts_per_week": stats.get("posts_per_week"),
            "format_mix_pct": stats.get("format_mix_pct"),
            "engagement": stats.get("engagement"),
            "video_duration": stats.get("video_duration"),
            "hashtag_strategy": stats.get("cta_effect"),
        },
        "classifications": sample_posts,
    }
    user = (
        "Données Instagram :\n" + json.dumps(payload, ensure_ascii=False) + "\n\n"
        "Schéma JSON attendu (toutes les clés obligatoires, focus Instagram) :\n"
        "{\n"
        '  "positioning": "comment cet influenceur se positionne sur Instagram",\n'
        '  "audience": "qui regarde ses Reels (centres d\'intérêt, niveau, attentes)",\n'
        '  "content_pillars": ["thème 1", "thème 2", ...],\n'
        '  "hook_patterns": ["type d\'accroche visuelle/parlée qui fonctionne", ...],\n'
        '  "structural_patterns": ["durée, format, musique, hashtags récurrents", ...],\n'
        '  "cta_strategy": "comment il appelle à l\'action (DM, lien bio, tag, save, follow)",\n'
        '  "strengths": ["point fort Instagram 1", ...],\n'
        '  "gaps": ["opportunité manquée 1", ...],\n'
        '  "actions_to_replicate": ["action concrète à répliquer 1", ...]\n'
        "}"
    )

    data = _call(system, user, max_tokens=4096, temperature=0.4)
    return StrategySynthesis(**data).model_dump()
