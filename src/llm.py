"""LLM-based classification and strategic synthesis (Claude / Anthropic)."""
from __future__ import annotations

import json
import os
import re
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


EDITORIAL_ROLES: dict[str, dict[str, str]] = {
    "performance": {
        "label": "Performance",
        "objective": "maximiser les signaux d'engagement avec un hook fort, une tension claire et un CTA net",
        "structure": "structure optimisée issue des meilleurs posts du benchmark, rythme nerveux, contraste fort",
    },
    "methodologie": {
        "label": "Méthodologie",
        "objective": "transmettre une méthode, un framework ou un apprentissage utile, même si le potentiel viral est plus faible",
        "structure": "progression pédagogique, étapes concrètes, exemples et limites plutôt qu'un hook sensationnaliste",
    },
    "autorite": {
        "label": "Autorité",
        "objective": "installer la crédibilité par une preuve, une expérience, un résultat ou un jugement professionnel",
        "structure": "preuve contextualisée, observation de terrain, nuance, pas de survente ni de promesse excessive",
    },
    "story": {
        "label": "Histoire",
        "objective": "raconter une histoire personnelle ou professionnelle qui rend le point de vue mémorable",
        "structure": "scène initiale, tension, bascule, enseignement léger ou implication concrète",
    },
    "quotidien": {
        "label": "Quotidien",
        "objective": "créer de la proximité avec une scène de vie, une visite, une coulisse ou une observation locale",
        "structure": "ton simple, détail concret, peu de packaging, pas forcément de grande leçon finale",
    },
    "opinion": {
        "label": "Opinion",
        "objective": "exprimer une prise de position simple et assumée qui ouvre la discussion",
        "structure": "thèse claire, 2-4 arguments, nuance, question finale possible",
    },
    "relationnel": {
        "label": "Relationnel",
        "objective": "entretenir la conversation et la proximité avec une question ouverte ou un partage humain",
        "structure": "format court à moyen, invitation sincère à répondre, pas de mécanique de commentaire forcée",
    },
}

_EDITORIAL_ROLE_ALIASES = {
    "auto": "auto",
    "mix": "auto",
    "automatique": "auto",
    "performance": "performance",
    "methodologie": "methodologie",
    "méthodologie": "methodologie",
    "methode": "methodologie",
    "méthode": "methodologie",
    "expertise": "methodologie",
    "autorite": "autorite",
    "autorité": "autorite",
    "authority": "autorite",
    "story": "story",
    "histoire": "story",
    "storytelling": "story",
    "quotidien": "quotidien",
    "daily": "quotidien",
    "coulisses": "quotidien",
    "opinion": "opinion",
    "relationnel": "relationnel",
    "conversation": "relationnel",
    "proximite": "relationnel",
    "proximité": "relationnel",
}

DEFAULT_EDITORIAL_MIX = ["performance", "methodologie", "quotidien"]
DEFAULT_IDEA_MIX = ["performance", "methodologie", "autorite", "story", "quotidien", "opinion", "relationnel"]


def normalize_editorial_role(role: str | None) -> str:
    """Return a supported editorial role key, or auto for the default mix."""
    key = (role or "auto").strip().lower().replace("-", "_")
    return _EDITORIAL_ROLE_ALIASES.get(key, "auto")


def editorial_role_sequence(role: str | None, count: int = 3) -> list[str]:
    """Resolve a requested role into the role sequence expected from the LLM."""
    normalized = normalize_editorial_role(role)
    if normalized != "auto":
        return [normalized for _ in range(count)]
    return [DEFAULT_EDITORIAL_MIX[i % len(DEFAULT_EDITORIAL_MIX)] for i in range(count)]


def _role_brief(role: str) -> dict[str, str]:
    spec = EDITORIAL_ROLES[role]
    return {
        "role": role,
        "label": spec["label"],
        "objectif": spec["objective"],
        "structure": spec["structure"],
    }


def _decorate_ideas_with_roles(ideas: list[dict]) -> list[dict]:
    for i, idea in enumerate(ideas):
        role = normalize_editorial_role(idea.get("editorial_role"))
        if role == "auto":
            role = DEFAULT_IDEA_MIX[i % len(DEFAULT_IDEA_MIX)]
        idea["editorial_role"] = role
        idea.setdefault("source_type", "benchmark_mix")
    return ideas


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


def generate_ideas(top_posts_examples: list[dict], benchmark: dict, count: int = 5) -> list[dict]:
    """Generate post ideas based on analyzed influencer insights."""
    top_examples_text = "\n\n".join(
        f"[{e.get('influencer', '?')} | {e.get('engagement', 0)} eng | hook: {e.get('hook_type', 'other')}]\n{e.get('text', '')[:400]}"
        for e in top_posts_examples[:8]
    )
    representative_examples = benchmark.get("representative_examples", [])
    representative_text = "\n\n".join(
        f"[{e.get('influencer', '?')} | {e.get('engagement', 0)} eng | hook: {e.get('hook_type', 'other')} | source: {e.get('source_type', 'representative')}]\n{e.get('text', '')[:400]}"
        for e in representative_examples[:8]
    )

    system = (
        "Tu es un stratège contenu LinkedIn. "
        "Tu proposes un mix éditorial réaliste en t'appuyant sur des données réelles : "
        "certains posts cherchent la performance, d'autres l'expertise, l'autorité, "
        "la proximité ou la conversation. "
        "Réponds UNIQUEMENT avec un objet JSON valide, sans markdown, sans texte avant/après."
    )
    user = (
        "Benchmarks issus de l'analyse des influenceurs LinkedIn de l'utilisateur :\n"
        + json.dumps(benchmark, ensure_ascii=False, indent=2)
        + "\n\nExemples des posts les plus performants :\n"
        + top_examples_text
        + "\n\nExemples moyens ou représentatifs à ne pas ignorer :\n"
        + representative_text
        + f"""

Propose exactement {count} idées de posts LinkedIn originales avec un mix de rôles éditoriaux.
N'optimise pas tout pour le même signal : couvre autant que possible ces rôles selon le nombre demandé :
{json.dumps([_role_brief(role) for role in DEFAULT_IDEA_MIX], ensure_ascii=False, indent=2)}

Pour chaque idée :
- Identifie un angle unique basé sur les patterns qui marchent OU sur des posts représentatifs utiles
- Propose un hook accrocheur (première ligne du post)
- Explique pourquoi cette idée est utile stratégiquement (performance, autorité, proximité, expertise...)
- Indique le type de hook et le niveau du funnel (TOFU/MOFU/BOFU)
- Renseigne `editorial_role` avec l'un des rôles supportés
- Renseigne `source_type` : top_performer | representative | strategic_gap | everyday_context

Schéma JSON attendu :
{{
  "ideas": [
    {{
      "title": "titre court de l'idée (5-10 mots)",
      "hook": "première ligne du post proposée",
      "hook_type": "stat+contrarian | story+result | question | list | bold_claim",
      "editorial_role": "performance | methodologie | autorite | story | quotidien | opinion | relationnel",
      "source_type": "top_performer | representative | strategic_gap | everyday_context",
      "funnel": "TOFU | MOFU | BOFU",
      "angle": "description de l'angle en 1-2 phrases",
      "why_it_works": "explication basée sur les données du corpus",
      "difficulty": "facile | moyen | avancé",
      "estimated_lift": "+X% vs post standard OU impact stratégique non chiffré"
    }}
  ]
}}"""
    )
    data = _call(system, user, max_tokens=4096, temperature=0.8)
    return _decorate_ideas_with_roles(data.get("ideas", []))


def analyze_dashboard_strategy(influencers_data: list[dict], growth_data: list[dict] | None = None) -> str:
    """Generate a deep strategic AI analysis of the dashboard data."""
    system = (
        "Tu es un stratège senior en marketing LinkedIn et personal branding. "
        "Tu analyses des données comparatives de plusieurs influenceurs pour en tirer "
        "des recommandations stratégiques concrètes et actionnables. "
        "Tu dois aller au-delà des chiffres : identifier les stratégies gagnantes, "
        "les corrélations entre formats/hooks/engagement, et recommander des actions précises. "
        "Réponds en markdown structuré (titres ##, listes, gras). Ne mets PAS de balises ```markdown."
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


def generate_posts(
    topic: str,
    top_posts_examples: list[dict],
    benchmark: dict,
    editorial_role: str | None = "auto",
) -> list[dict]:
    """Generate 3 LinkedIn post variants with explicit editorial roles."""
    requested_role = normalize_editorial_role(editorial_role)
    roles = editorial_role_sequence(requested_role, count=3)
    top_examples_text = "\n\n".join(
        f"[{e.get('influencer', '?')} | {e.get('engagement', 0)} eng | hook: {e.get('hook_type', 'other')}]\n{e.get('text', '')[:600]}"
        for e in top_posts_examples[:6]
    )
    representative_examples = benchmark.get("representative_examples", [])
    representative_text = "\n\n".join(
        f"[{e.get('influencer', '?')} | {e.get('engagement', 0)} eng | hook: {e.get('hook_type', 'other')} | source: {e.get('source_type', 'representative')}]\n{e.get('text', '')[:600]}"
        for e in representative_examples[:8]
    )

    system = (
        "Tu es un stratège LinkedIn senior. "
        "Tu sais générer des posts qui n'ont pas tous le même rôle : performance, méthode, "
        "autorité, histoire, quotidien, opinion ou relationnel. "
        "Réponds UNIQUEMENT avec un objet JSON valide, sans markdown, sans texte avant/après."
    )
    user = (
        f'Sujet du post à créer : "{topic}"\n\n'
        "Benchmarks issus de l'analyse des influenceurs LinkedIn de l'utilisateur :\n"
        + json.dumps(benchmark, ensure_ascii=False, indent=2)
        + "\n\nExemples des posts les plus performants :\n"
        + top_examples_text
        + "\n\nExemples moyens ou représentatifs à utiliser surtout pour les rôles non-performance :\n"
        + representative_text
        + f"""

Rôle demandé par l'utilisateur : {requested_role}
Plan éditorial imposé pour les 3 variants :
{json.dumps([_role_brief(role) for role in roles], ensure_ascii=False, indent=2)}

Génère exactement 3 variants de posts LinkedIn.

Règles impératives :
- Chaque variant doit renseigner `editorial_role` et respecter le rôle prévu dans le plan ci-dessus.
- Les 3 variants doivent avoir des structures différentes : pas le même hook, pas le même déroulé, pas le même CTA.
- Si le rôle est `performance`, tu peux t'inspirer des top posts, renforcer hook/tension/CTA et viser l'engagement.
- Si le rôle est `methodologie`, privilégie clarté, étapes utiles, exemple concret et pédagogie.
- Si le rôle est `autorite`, installe la crédibilité par une preuve, une expérience ou une observation professionnelle sans sur-vendre.
- Si le rôle est `story`, raconte une vraie scène avec tension et bascule plutôt qu'un framework générique.
- Si le rôle est `quotidien`, écris un post simple, humain, contextuel, avec détail de terrain ; aucune grande leçon finale obligatoire.
- Si le rôle est `opinion`, assume une prise de position claire et nuancée.
- Si le rôle est `relationnel`, favorise la conversation et la proximité ; évite les mécaniques artificielles.
- Ne force PAS une structure hook → framework → triple CTA pour tous les posts.
- Un CTA est optionnel pour les rôles quotidien, story, opinion et relationnel ; s'il existe, il doit être naturel.
- Langue : français.
- Ne PAS mettre de balises markdown dans le texte du post.

Schéma JSON attendu (toutes les clés obligatoires) :
{
  "variants": [
    {
      "editorial_role": "performance | methodologie | autorite | story | quotidien | opinion | relationnel",
      "hook_type": str,
      "strategy": "1-2 phrases expliquant le rôle stratégique de ce variant",
      "predicted_lift": "ex: +40-80% vs post standard OU 'proximité / autorité, performance non prioritaire'",
      "post": "texte complet du post prêt à publier"
    }
  ]
}"""
    )
    data = _call(system, user, max_tokens=6000, temperature=0.7)
    variants = data.get("variants", [])
    for i, variant in enumerate(variants):
        role = normalize_editorial_role(variant.get("editorial_role"))
        if role == "auto":
            role = roles[i % len(roles)]
        variant["editorial_role"] = role
        variant.setdefault("predicted_lift", "Rôle stratégique, performance non prioritaire")
    return variants
