"""Base de hooks Instagram/TikTok + sélection personnalisée via LLM."""
from __future__ import annotations

import json
import os
import random
from typing import Any

HOOK_TEMPLATES: list[str] = [
    "personne ne parle de ça et pourtant...",
    "si tu es ... tu es en train de louper une opportunité pour...",
    "ce que les ... ne te disent pas",
    "ne fais pas comme 99% des...",
    "This may be controversial but ___",
    '"WHAT IF I TOLD YOU..',
    '"Here\'s How"..',
    '"You need to try this"',
    '"Do not do action before you try this"',
    '"This is why I\'ll NEVER go back to X"',
    "X Mistakes you're making with __",
    "Have you heard about _ ?",
    "___ people stop scrolling!",
    "Everything you knew about ___ is 100% WRONG!",
    "(niche) I need your help please",
    "I can't believe what I just discovered!",
    "If you like _ you need _",
    "I died when I found this out!",
    "I have something to confess",
    "This is something I wish I knew when starting out in (niche)",
    "I really wish I knew this when starting out (niche)",
    "Here's a sleep tip that will blow your mind",
    "5 Healthy things you can do to improve your life right now",
    "You don't need (expensive product) to solve (pain point)",
    "You're probably using (product) wrong, heres the correct way",
    "If you're in the (niche industry) YOU NEED this right now",
    "How much should you be paying for (service)",
    "3 free apps I use to help with (niche)",
    "Here's something REALLY Important I wish I learned",
    "3 Big Mistakes You're Making When _",
    "Calling all (target audience)",
    "This is how I got (x)",
    "Here are ___ tips to get rid of ___",
    "You need to stop _, here's why",
    "This feels illegal to know: _",
    "I wish I knew about these (x) earlier",
    "Stop scrolling if you want to do ___",
    "Come with me to do ___",
    "Here's a simple hack to help you do ___",
    "Do you have problems with ___? Well I just found the perfect solution!",
    "Here's how I achieved ___ in only (quantity) months/years!",
    "This is the only thing you need to know about ___!",
    "Don't make this mistake when doing ___",
    "What would you do if ___?",
    "Why does no one talk about this?",
    "If you want ___, avoid doing this!",
    "Don't believe this ___ myth!",
    "This ___ will blow your mind!",
    "Unpopular opinion:",
    "Did you know that ___?",
    "You don't want to miss this!",
    "This is a reminder to do ___",
    "This is the story of ___",
    "This hack will save you hours on ___",
    "If you want to do ___, you need to do this!",
    "Red flags to look for in ___",
    "5 mistakes you are probably making when you ___",
    "Try this one trick to get ___",
    "This free tool is a game changer!",
    "Here are 3 signs that you should ___",
    "This one simple mistake could be costing you ___",
    "This hack changed my life!",
    "Predictions on the Future of ___",
    "Why 99% of (audience) won't _",
    "Get Rid of Your ___ Once and For All",
    "OMG you won't believe this",
    "Please stop trying to ___",
    "If you ___ listen up",
    "# Reasons Not to ___",
    "How to make sure you'll never ___",
    "Instead of doing/using ___ do ___.",
    "Before you scroll ____",
    "I spent ____ years designing this",
    "Unpopular opinion...",
    "Did you know _____ just blew up in popularity?",
    "if you do ____ you need to hear this!!",
    '"Got X Problem?"',
    '"Top 3 Tips about X"',
    '"How to get Y in 24 Hours"',
    '"Why is nobody talking about Y"',
    '"I wish I had Y earlier"',
    '"Don\'t make this mistake if you\'re using X"',
    '"This is a reminder to do.."',
    '"A huge realization I had about Y"',
    '"X will save you hours"',
    '"This trick will save you hours"',
    '"This is how you can get Y in 30 Days"',
    "Want to know the secret to ____?",
    "Unpopular opinion... (X statement)",
    "Stop scrolling if you suffer with X",
    "Warning to [target market]",
    "The WORST things to do before ___",
    '"Here\'s a hot take in (niche)"',
    '"Avoid these 3 things if you\'re trying to (goal)"',
    "POV: _",
    "Maturing is realizing ____",
    "Here is why ____",
    "I don't know who needs to hear this but you're probably using (niche/product) wrong",
    "I promise you've never X",
    "Did you know...",
    "Here is a tip from a professional ____ that can ____",
    "Here is the number #1 thing _____ should know",
    "So this just happened at _____",
    "Here's how I did _____ in ____ (amount of time)",
    "Why is nobody talking about _____?",
    "I bought _____ so you don't have to",
    "This is why your ____ isn't working",
    "Here's what school doesn't teach you:",
    "The ugly truth about ___",
    "Here's how I solved (problem) in (number of days) with this one simple trick",
    "Save this video for the next time you need to (action)",
    "You guys keep asking for ___ (Niche/solution)",
    "____ things I wish I knew before I _____",
    "How I got ___ in 24 hours",
]


def select_hooks(user_context: dict[str, Any], count: int = 10) -> list[str]:
    """Sélectionne et personnalise les hooks les plus adaptés au profil utilisateur.

    Sélectionne aléatoirement count*3 hooks depuis la base, puis appelle Claude
    pour choisir les `count` hooks les plus pertinents et les personnaliser
    (placeholders remplacés par des infos du profil éditorial).
    """
    # Sanity check
    count = max(1, min(count, len(HOOK_TEMPLATES)))

    # Pré-sélection aléatoire pour limiter le prompt
    pool = random.sample(HOOK_TEMPLATES, min(count * 3, len(HOOK_TEMPLATES)))

    try:
        from anthropic import Anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            # Fallback sans LLM : retourner les hooks tels quels
            return pool[:count]

        client = Anthropic(api_key=api_key)

        context_lines = []
        for k, v in (user_context or {}).items():
            if v:
                context_lines.append(f"- {k}: {v}")
        context_text = "\n".join(context_lines) if context_lines else "Aucun contexte disponible."

        pool_text = "\n".join(f"{i+1}. {h}" for i, h in enumerate(pool))

        system = (
            "Tu es un expert en contenu Instagram et réseaux sociaux. "
            "Ta mission : choisir les hooks les plus percutants pour ce profil "
            "et les personnaliser avec ses infos (secteur, audience, offre, ton). "
            "Remplace tous les placeholders (___,  (niche), (product), (pain point), "
            "(audience), X, Y, etc.) par des éléments concrets du profil. "
            "Réponds UNIQUEMENT avec un tableau JSON valide de chaînes de caractères, "
            "sans markdown, sans texte avant/après."
        )

        user_msg = (
            f"Profil éditorial du client :\n{context_text}\n\n"
            f"Hooks disponibles :\n{pool_text}\n\n"
            f"Sélectionne exactement {count} hooks parmi cette liste "
            f"(les plus adaptés au profil) et personnalise-les. "
            f"Réponds avec un tableau JSON de {count} chaînes."
        )

        resp = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7"),
            max_tokens=1024,
            messages=[{"role": "user", "content": user_msg}],
            system=system,
        )

        raw = resp.content[0].text.strip()
        # Nettoyer les éventuels blocs ```json ... ```
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        hooks = json.loads(raw)
        if isinstance(hooks, list):
            return [str(h) for h in hooks[:count]]
        return pool[:count]

    except Exception:
        # En cas d'erreur LLM, retourner les hooks bruts sans personnalisation
        return pool[:count]
