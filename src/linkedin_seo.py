"""Audit SEO d'un profil LinkedIn — référencement dans la barre de recherche.

Le trou comblé : l'analyse d'onboarding parlait du *contenu* (ce qu'il publie)
et jamais du *profil* (comment on le trouve). Or LinkedIn est d'abord un moteur
de recherche : recruteurs et clients y tapent un métier, et un profil mal
renseigné est invisible quoi qu'il publie.

Trois propriétés à conserver si ce fichier est retouché :

1. **Zéro scrape supplémentaire.** Tous les signaux viennent de
   `normalize_profile(...)["seo"]`, c'est-à-dire de champs que les deux acteurs
   Apify renvoyaient DÉJÀ et que la normalisation jetait. Un audit qui
   déclencherait un second run coûterait à chaque onboarding.
2. **Les faits d'abord, le modèle ensuite.** `collect_findings()` est une
   fonction PURE : elle décide seule de ce qui est objectivement absent (pas de
   bannière, pas d'URL personnalisée, moins de 5 compétences…). Le modèle ne
   sert qu'à formuler et à juger ce qui demande du jugement (le titre est-il
   parlant ? la bannière dit-elle quelque chose ?). Un modèle en panne dégrade
   la formulation, jamais l'exactitude des constats.
3. **Rien plutôt que n'importe quoi.** Sans données de profil (entrée par un
   site web, scrape échoué), l'audit n'existe pas — il ne dit pas « ton profil
   est incomplet » à quelqu'un dont on n'a jamais lu le profil.

Source des règles : la synthèse « SEO LinkedIn » d'Emmanuel Bismuth fournie par
Alex, **distillée en principes** et réécrite — le texte d'origine n'est pas
recopié. Deux points de la source sont volontairement ÉCARTÉS parce qu'ils sont
datés ou hors sujet ici : le score SSI (il exige Sales Navigator et ne se lit
pas depuis un scrape) et la consigne « ajoute 10-15 relations par jour » (c'est
de la prospection, pas du référencement de profil — et l'app cadence déjà ses
propres envois).
"""
from __future__ import annotations

import json
from typing import Any

from src import llm
from src.net_guard import NetGuardError, guarded_download

# Bannière : bornée petit. Une image de couverture LinkedIn pèse quelques
# centaines de Ko ; au-delà on ne télécharge pas (protection mémoire, même
# raison que les autres téléchargements du repo).
_BANNER_MAX_BYTES = 6 * 1024 * 1024
_BANNER_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_BANNER_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_MEDIA_TYPE_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# Seuils repris de la source, tenus en un seul endroit pour qu'ils se
# discutent (et se corrigent) sans relire le prompt.
MIN_SKILLS = 10
MIN_HEADLINE_CHARS = 40
MIN_ABOUT_CHARS = 300
MIN_RECOMMENDATIONS = 1

# Titres qui ne se cherchent pas : personne ne tape « fondateur » dans LinkedIn
# pour trouver un prestataire. Minuscules, comparaison sur le titre entier.
_VAGUE_HEADLINES = frozenset({
    "ceo", "founder", "fondateur", "fondatrice", "co-founder", "cofondateur",
    "entrepreneur", "entrepreneuse", "consultant", "consultante", "freelance",
    "indépendant", "independant", "expert digital", "digital expert",
    "business owner", "dirigeant", "dirigeante", "manager", "directeur",
})

# Formulations qui affaiblissent le profil (posture de demandeur).
_WEAK_SIGNALS = ("open to work", "à la recherche", "a la recherche", "disponible immédiatement")


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def collect_findings(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Constats OBJECTIFS sur le profil — aucun jugement, aucun appel modèle.

    Chaque constat porte `ok` (respecté ou non), un libellé de critère et le
    fait mesuré. C'est ce qui permet à l'écran d'afficher une check-list vraie
    même si le modèle tombe.
    """
    profile = profile or {}
    seo = profile.get("seo") if isinstance(profile.get("seo"), dict) else {}
    headline = _text(profile.get("headline"))
    about = _text(profile.get("summary"))
    skills = [s for s in (seo.get("skills") or []) if isinstance(s, str) and s.strip()]
    titles = [t for t in (seo.get("job_titles") or []) if isinstance(t, str) and t.strip()]
    identifier = _text(seo.get("public_identifier"))
    banner = _text(seo.get("banner_url"))
    recos = int(seo.get("recommendations_count") or 0)

    findings: list[dict[str, Any]] = []

    def add(key: str, label: str, ok: bool, detail: str) -> None:
        findings.append({"key": key, "label": label, "ok": ok, "detail": detail})

    add(
        "headline", "Titre du profil",
        bool(headline) and len(headline) >= MIN_HEADLINE_CHARS
        and headline.lower().strip() not in _VAGUE_HEADLINES,
        f"{len(headline)} caractères" if headline else "vide",
    )
    add(
        "about", "Section Infos",
        len(about) >= MIN_ABOUT_CHARS,
        f"{len(about)} caractères" if about else "vide",
    )
    add(
        "skills", "Compétences",
        len(skills) >= MIN_SKILLS,
        f"{len(skills)} déclarée{'s' if len(skills) > 1 else ''}",
    )
    add(
        "banner", "Bannière",
        bool(banner),
        "personnalisée" if banner else "celle par défaut de LinkedIn",
    )
    # Une URL par défaut porte le hash que LinkedIn ajoute au nom (ex.
    # `martin-mourot-547097b6`) : la présence de chiffres en fin de segment est
    # le marqueur fiable, pas la longueur.
    custom_url = bool(identifier) and not _looks_autogenerated(identifier)
    add(
        "url", "URL personnalisée",
        custom_url,
        f"/in/{identifier}" if identifier else "inconnue",
    )
    add(
        "recommendations", "Recommandations",
        recos >= MIN_RECOMMENDATIONS,
        f"{recos} reçue{'s' if recos > 1 else ''}",
    )
    add(
        "titles", "Intitulés de postes",
        bool(titles) and not any(t.lower().strip() in _VAGUE_HEADLINES for t in titles[:2]),
        titles[0] if titles else "aucun poste lisible",
    )
    weak = [w for w in _WEAK_SIGNALS if w in (headline + " " + about).lower()]
    if weak or seo.get("open_to_work"):
        add(
            "posture", "Posture",
            False,
            "le profil se présente en demandeur (« ouvert aux opportunités »)",
        )
    return findings


def _looks_autogenerated(identifier: str) -> bool:
    """`prenom-nom-547097b6` = URL laissée par défaut ; `prenom-nom-seo` = choisie."""
    tail = identifier.rsplit("-", 1)[-1] if "-" in identifier else ""
    return len(tail) >= 6 and any(c.isdigit() for c in tail) and tail.isalnum()


def score(findings: list[dict[str, Any]]) -> int:
    """Score sur 100, arrondi — juste la part de critères respectés."""
    if not findings:
        return 0
    ok = sum(1 for f in findings if f.get("ok"))
    return round(100 * ok / len(findings))


def fetch_banner(url: str) -> tuple[str, bytes] | None:
    """Télécharge la bannière pour la faire regarder au modèle.

    Best-effort et anti-SSRF (`net_guard`) : l'URL vient d'un scrape, donc
    d'une source qu'on ne contrôle pas. Un échec rend `None` — l'audit se
    poursuit sans le volet visuel plutôt que de tomber.
    """
    if not url:
        return None
    try:
        filename, data, _ctype = guarded_download(
            url,
            allowed_exts=_BANNER_EXTS,
            default_ext=".jpg",
            max_bytes=_BANNER_MAX_BYTES,
            content_type_ext_map=_BANNER_CONTENT_TYPES,
            error_cls=NetGuardError,
            filename_stem="banner",
        )
    except Exception:
        return None
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".jpg"
    return _MEDIA_TYPE_BY_EXT.get(ext, "image/jpeg"), data


_RULES = """Règles de référencement LinkedIn (le profil est indexé comme une page web) :
- Le TITRE est le champ le plus fort. Il doit contenir les mots que le client tape (métier + spécialité + preuve), pas un statut ; « CEO », « Founder », « Freelance », « Expert digital » ne se cherchent pas.
- Les mots-clés doivent être ceux du CLIENT, pas le jargon interne. Ils se répètent naturellement dans le titre, la section Infos, les intitulés de postes.
- La section Infos est une page de vente, pas un CV : accroche orientée client, problème compris, preuve chiffrée, appel à l'action et moyen de contact.
- Les intitulés de postes (actuels et passés) sont indexés : ils doivent nommer le métier, pas le grade.
- Les compétences pèsent dans le classement : au moins dix, en rapport avec le métier, les plus stratégiques en tête.
- Une URL personnalisée (prenom-nom-motclé) vaut mieux qu'une URL à chiffres.
- Les recommandations reçues sont de la preuve sociale ET du texte indexé.
- La bannière est le premier message visible : elle doit annoncer la spécialité ou le bénéfice client, en gros (lisible sur mobile), sans y répéter le nom.
- Une posture de demandeur (« ouvert aux opportunités », « disponible ») affaiblit la perception : mieux vaut se présenter comme la solution."""


def audit(profile: dict[str, Any] | None, *, with_banner: bool = True) -> dict[str, Any] | None:
    """Audit complet : constats mesurés + lecture du modèle (bannière incluse).

    Rend `None` si aucun profil LinkedIn n'a été lu — on n'audite pas un compte
    qu'on n'a pas vu.
    """
    profile = profile or {}
    if not (_text(profile.get("headline")) or _text(profile.get("name")) or profile.get("seo")):
        return None

    findings = collect_findings(profile)
    seo = profile.get("seo") if isinstance(profile.get("seo"), dict) else {}
    banner_url = _text(seo.get("banner_url"))
    banner = fetch_banner(banner_url) if (with_banner and banner_url) else None

    result: dict[str, Any] = {
        "score": score(findings),
        "findings": findings,
        "has_banner": bool(banner_url),
        "banner_reviewed": bool(banner),
        "banner_url": banner_url,
        "keywords": [],
        "priorities": [],
        "banner_verdict": "",
    }

    facts = {
        "titre": _text(profile.get("headline")),
        "infos": _text(profile.get("summary"))[:2000],
        "intitules_de_postes": (seo.get("job_titles") or [])[:8],
        "competences": (seo.get("skills") or [])[:20],
        "url_publique": _text(seo.get("public_identifier")),
        "recommandations_recues": int(seo.get("recommendations_count") or 0),
        "banniere_personnalisee": bool(banner_url),
        "constats_mesures": findings,
    }
    banner_rule = (
        "- banner_verdict : tu VOIS la bannière en première image. Dis en une phrase "
        "ce qu'elle communique et ce qui manque (message, lisibilité sur mobile, preuve). "
        "Ne décris pas l'image : juge si elle vend."
        if banner
        else "- banner_verdict : le profil n'a pas de bannière personnalisée (ou elle n'a pas pu être "
        "lue). Dis en une phrase ce qu'une bannière devrait annoncer pour CE métier."
    )
    system = (
        "Tu es un spécialiste du référencement des profils LinkedIn. Tu es franc et "
        "concret. Tu t'appuies UNIQUEMENT sur les faits fournis (et sur l'image de "
        "bannière quand elle est là). Tu n'inventes aucun chiffre. Réponds "
        "UNIQUEMENT en JSON valide, sans markdown."
    )
    user = (
        _RULES
        + "\n\nProfil à auditer :\n"
        + json.dumps(facts, ensure_ascii=False, indent=2)
        + f"""

Règles de sortie :
- Français, tutoiement, ton direct.
- keywords : 4 à 8 mots-clés que SES clients taperaient pour le trouver, déduits de son métier réel. Pas de jargon interne, pas de hashtags.
- priorities : exactement 3 actions, la plus rentable d'abord, ≤ 14 mots chacune, formulées à l'impératif et spécifiques à CE profil (cite son métier, pas « optimise ton titre »).
{banner_rule}

Schéma JSON attendu :
{{"keywords": ["…"], "priorities": ["…", "…", "…"], "banner_verdict": "…"}}"""
    )

    try:
        data = llm._call(
            system,
            user,
            max_tokens=1200,
            temperature=0.3,
            images=[banner] if banner else None,
        )
    except Exception:
        # Best-effort : les constats mesurés restent affichables tels quels.
        return result

    if isinstance(data, dict):
        result["keywords"] = [
            k.strip().lstrip("#") for k in (data.get("keywords") or [])
            if isinstance(k, str) and k.strip()
        ][:8]
        result["priorities"] = [
            p.strip() for p in (data.get("priorities") or [])
            if isinstance(p, str) and p.strip()
        ][:3]
        verdict = data.get("banner_verdict")
        result["banner_verdict"] = verdict.strip() if isinstance(verdict, str) else ""
    return result
