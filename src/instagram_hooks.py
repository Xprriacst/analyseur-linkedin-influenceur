"""Base de hooks Instagram/TikTok (en français) + sélection personnalisée via LLM."""
from __future__ import annotations

import json
import os
import random
from typing import Any

# Tous les hooks sont en français. Les placeholders ((niche), (product),
# (pain point), ___, X, Y…) sont remplis par le LLM avec le contexte du user.
HOOK_TEMPLATES: list[str] = [
    "personne ne parle de ça et pourtant...",
    "si tu es ... tu es en train de louper une opportunité pour...",
    "ce que les ... ne te disent pas",
    "ne fais pas comme 99% des...",
    "C'est peut-être polémique, mais ___",
    "ET SI JE TE DISAIS QUE...",
    "Voici comment...",
    "Tu dois absolument essayer ça",
    "Ne fais pas (action) avant d'avoir essayé ça",
    "Voilà pourquoi je ne reviendrai JAMAIS à X",
    "X erreurs que tu fais avec __",
    "Tu as déjà entendu parler de _ ?",
    "___ arrêtez de scroller !",
    "Tout ce que tu crois savoir sur ___ est 100% FAUX !",
    "(niche), j'ai besoin de ton aide s'il te plaît",
    "Je n'arrive pas à croire ce que je viens de découvrir !",
    "Si tu aimes _, il te faut _",
    "Je suis tombé des nues en apprenant ça !",
    "J'ai quelque chose à avouer",
    "Voici ce que j'aurais aimé savoir en débutant dans (niche)",
    "J'aurais vraiment aimé savoir ça en démarrant (niche)",
    "Voici une astuce sommeil qui va te bluffer",
    "5 choses saines à faire pour améliorer ta vie dès maintenant",
    "Tu n'as pas besoin de (produit cher) pour régler (pain point)",
    "Tu utilises probablement (produit) mal, voici la bonne méthode",
    "Si tu es dans (secteur), il te faut ça tout de suite",
    "Combien devrais-tu vraiment payer pour (service) ?",
    "3 applis gratuites que j'utilise pour (niche)",
    "Voici un truc VRAIMENT important que j'aurais aimé apprendre",
    "3 grosses erreurs que tu fais quand _",
    "Avis à tous les (audience cible)",
    "Voici comment j'ai obtenu (x)",
    "Voici ___ astuces pour te débarrasser de ___",
    "Tu dois arrêter de _, voici pourquoi",
    "Ça semble illégal de savoir ça : _",
    "J'aurais aimé connaître ces (x) plus tôt",
    "Arrête de scroller si tu veux ___",
    "Viens avec moi faire ___",
    "Voici une astuce simple pour t'aider à ___",
    "Tu as des problèmes avec ___ ? Je viens de trouver la solution parfaite !",
    "Voici comment j'ai atteint ___ en seulement (quantité) mois/ans !",
    "C'est la seule chose à savoir sur ___ !",
    "Ne fais pas cette erreur quand tu fais ___",
    "Que ferais-tu si ___ ?",
    "Pourquoi personne n'en parle ?",
    "Si tu veux ___, évite de faire ça !",
    "Ne crois pas ce mythe sur ___ !",
    "Ce ___ va te bluffer !",
    "Avis impopulaire :",
    "Tu savais que ___ ?",
    "Tu ne veux pas rater ça !",
    "Ceci est un rappel pour faire ___",
    "Voici l'histoire de ___",
    "Cette astuce va te faire gagner des heures sur ___",
    "Si tu veux faire ___, tu dois faire ça !",
    "Les signaux d'alerte à repérer dans ___",
    "5 erreurs que tu fais probablement quand tu ___",
    "Essaie cette astuce pour obtenir ___",
    "Cet outil gratuit change tout !",
    "Voici 3 signes que tu devrais ___",
    "Cette simple erreur pourrait te coûter ___",
    "Cette astuce a changé ma vie !",
    "Mes prédictions sur l'avenir de ___",
    "Pourquoi 99% des (audience) ne vont pas _",
    "Débarrasse-toi de ton ___ une bonne fois pour toutes",
    "OMG tu ne vas pas y croire",
    "Arrête d'essayer de ___, s'il te plaît",
    "Si tu ___, écoute bien",
    "# raisons de NE PAS ___",
    "Comment être sûr de ne jamais ___",
    "Au lieu de faire/utiliser ___, fais ___.",
    "Avant de scroller ____",
    "J'ai passé ____ ans à concevoir ça",
    "Avis impopulaire...",
    "Tu savais que _____ vient d'exploser en popularité ?",
    "Si tu fais ____, tu dois entendre ça !!",
    "Un problème de X ?",
    "Top 3 des astuces sur X",
    "Comment obtenir Y en 24h",
    "Pourquoi personne ne parle de Y ?",
    "J'aurais aimé avoir Y plus tôt",
    "Ne fais pas cette erreur si tu utilises X",
    "Ceci est un rappel pour faire...",
    "Une grosse prise de conscience que j'ai eue sur Y",
    "X va te faire gagner des heures",
    "Cette astuce va te faire gagner des heures",
    "Voici comment obtenir Y en 30 jours",
    "Tu veux connaître le secret de ____ ?",
    "Avis impopulaire... (X)",
    "Arrête de scroller si tu souffres de X",
    "Avertissement aux (audience cible)",
    "Les PIRES choses à faire avant ___",
    "Voici mon avis tranché sur (niche)",
    "Évite ces 3 choses si tu veux (objectif)",
    "POV : _",
    "Mûrir, c'est réaliser que ____",
    "Voici pourquoi ____",
    "Je ne sais pas qui a besoin de l'entendre, mais tu utilises probablement (niche/produit) mal",
    "Je te promets que tu n'as jamais X",
    "Tu savais que...",
    "Voici une astuce de pro ____ qui peut ____",
    "Voici LA chose n°1 que ____ devrait savoir",
    "Donc ça vient d'arriver à _____",
    "Voici comment j'ai fait _____ en ____ (durée)",
    "Pourquoi personne ne parle de _____ ?",
    "J'ai acheté _____ pour que tu n'aies pas à le faire",
    "Voici pourquoi ton ____ ne fonctionne pas",
    "Voici ce que l'école ne t'apprend pas :",
    "La vérité qui dérange sur ___",
    "Voici comment j'ai résolu (problème) en (nombre de jours) avec cette astuce toute simple",
    "Enregistre cette vidéo pour la prochaine fois que tu dois (action)",
    "Vous me réclamez sans cesse ___ (niche/solution)",
    "____ choses que j'aurais aimé savoir avant de _____",
    "Comment j'ai obtenu ___ en 24h",
]


def select_hooks(user_context: dict[str, Any], count: int = 8, topic: str | None = None) -> list[str]:
    """Sélectionne et personnalise les hooks les plus adaptés au profil utilisateur.

    Sélectionne aléatoirement count*3 hooks depuis la base, puis appelle Claude
    pour choisir les `count` hooks les plus pertinents et les personnaliser
    (placeholders remplacés par des infos du profil éditorial). Si `topic` est
    fourni, les hooks sont orientés vers ce sujet/thème. Sortie toujours en français.

    En cas d'absence de clé API ou d'erreur LLM, renvoie un fallback de hooks
    bruts (déjà en français) sans placeholder résiduel.
    """
    # Sanity check
    count = max(1, min(count, len(HOOK_TEMPLATES)))

    # Pré-sélection aléatoire pour limiter le prompt
    pool = random.sample(HOOK_TEMPLATES, min(count * 3, len(HOOK_TEMPLATES)))

    def _fallback() -> list[str]:
        # Privilégier les hooks "prêts à l'emploi" (sans placeholder) pour ne
        # jamais afficher de gabarit cassé type "___" / "(niche)".
        ready = [h for h in pool if not _has_placeholder(h)]
        ready += [h for h in HOOK_TEMPLATES if not _has_placeholder(h) and h not in ready]
        return ready[:count]

    try:
        from anthropic import Anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return _fallback()

        client = Anthropic(api_key=api_key)

        context_lines = []
        for k, v in (user_context or {}).items():
            if v:
                context_lines.append(f"- {k}: {v}")
        context_text = "\n".join(context_lines) if context_lines else "Aucun contexte disponible."

        pool_text = "\n".join(f"{i+1}. {h}" for i, h in enumerate(pool))

        topic_line = f"\nSujet/thème à privilégier pour les hooks : {topic.strip()}\n" if (topic and topic.strip()) else ""

        system = (
            "Tu es un expert en contenu Instagram et réseaux sociaux. "
            "Ta mission : choisir les hooks les plus percutants pour ce profil "
            "et les personnaliser avec ses infos (secteur, audience, offre, ton). "
            "Remplace tous les placeholders (___,  (niche), (product), (pain point), "
            "(audience), X, Y, etc.) par des éléments concrets du profil. "
            "IMPÉRATIF : tous les hooks doivent être rédigés EN FRANÇAIS, "
            "naturels et percutants (traduis tout terme anglais résiduel). "
            "Réponds UNIQUEMENT avec un tableau JSON valide de chaînes de caractères, "
            "sans markdown, sans texte avant/après."
        )

        user_msg = (
            f"Profil éditorial du client :\n{context_text}\n"
            f"{topic_line}\n"
            f"Hooks disponibles :\n{pool_text}\n\n"
            f"Sélectionne exactement {count} hooks parmi cette liste "
            f"(les plus adaptés au profil{' et au sujet' if topic_line else ''}) et personnalise-les. "
            f"Rends-les tous en français. "
            f"Réponds avec un tableau JSON de {count} chaînes."
        )

        from src.llm import thinking_kwargs

        model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": user_msg}],
            system=system,
            **thinking_kwargs(model),
        )

        raw = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        ).strip()
        # Nettoyer les éventuels blocs ```json ... ```
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        hooks = json.loads(raw)
        if isinstance(hooks, list) and hooks:
            return [str(h) for h in hooks[:count]]
        return _fallback()

    except Exception:
        return _fallback()


def _has_placeholder(hook: str) -> bool:
    """True si le hook contient un placeholder non rempli (gabarit cassé)."""
    markers = ("___", "__", " _ ", "(niche", "(product", "(produit", "(pain", "(audience",
               "(service", "(secteur", "(goal", "(objectif", "(target", "(quantity",
               "(quantité", "(durée", "(action", "(problème", "(nombre", "(x)", "[target")
    h = hook.lower()
    if h.endswith(" _") or h.endswith("_"):
        return True
    return any(m in h for m in markers)
