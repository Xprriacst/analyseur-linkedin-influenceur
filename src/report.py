"""Markdown report rendering."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote


REPORTS_DIR = Path("reports")

# Libellés grand public ; le terme technique reste visible en italique discret.
HOOK_LABELS = {
    "question": "Question directe",
    "story": "Histoire / anecdote",
    "stat": "Chiffre choc",
    "bold_claim": "Affirmation tranchée",
    "list": "Liste",
    "result": "Résultat chiffré",
    "contrarian": "Contre-pied",
    "other": "Autre",
}

STAGE_LABELS = {
    "TOFU": "Attraction",
    "MOFU": "Éducation",
    "BOFU": "Conversion",
}

FORMAT_LABELS = {
    "text": "Texte seul",
    "image": "Image",
    "video": "Vidéo",
    "carousel": "Carrousel",
    "document": "Document PDF",
    "article": "Article",
    "repost": "Repost (partage)",
    "poll": "Sondage",
}


def _hook_label(key: str) -> str:
    return f"{HOOK_LABELS.get(key, key)} _({key})_"


def _stage_label(key: str) -> str:
    return f"{STAGE_LABELS.get(key, key)} _({key})_"


def _format_label(key: str) -> str:
    return FORMAT_LABELS.get(key, key)


def _bar(value: float, total: float, width: int = 20) -> str:
    if total <= 0:
        return ""
    filled = int(round((value / total) * width))
    return "█" * filled + "░" * (width - filled)


def _stage_distribution(classifications: list[dict]) -> dict[str, int]:
    return dict(Counter(c["stage"] for c in classifications))


def _hook_distribution(classifications: list[dict]) -> dict[str, int]:
    return dict(Counter(c["hook_type"] for c in classifications))


def render_markdown(
    handle: str,
    profile_url: str,
    stats: dict,
    classifications: list[dict],
    synthesis: dict,
    posts: list[dict],
    profile: dict | None = None,
    patterns: dict | None = None,
    cta_stats: dict | None = None,
    usage: dict | None = None,
) -> str:
    stage_dist = _stage_distribution(classifications)
    hook_dist = _hook_distribution(classifications)
    total_class = sum(stage_dist.values()) or 1
    profile = profile or {}
    patterns = patterns or {}
    cta_stats = cta_stats or {}
    usage = usage or {}

    display_name = (profile or {}).get("name") or unquote(handle)
    lines: list[str] = []
    lines.append(f"# Stratégie LinkedIn — {display_name}")
    lines.append("")
    lines.append(f"_Profil_ : [{unquote(handle)}]({profile_url})  ")
    lines.append(f"_Analyse générée le_ : {datetime.now().strftime('%Y-%m-%d %H:%M')}  ")
    excluded = stats.get("excluded_recent_count", 0)
    suffix = f" (— {excluded} post(s) <24h exclus)" if excluded else ""
    span = f"sur {stats['span_days']} jours" if stats.get("span_days") else "(dates indisponibles)"
    lines.append(f"_Posts analysés_ : **{stats['count']}** {span}{suffix}")
    lines.append("")

    # ========== BLOC 1 : Profil en chiffres (toujours affiché, même si le scrape profil a échoué) ==========
    lines.append("## Profil en chiffres")
    lines.append("")
    headline = profile.get("headline") or ""
    location = profile.get("location") or ""
    meta = " · ".join(filter(None, [display_name, headline, location]))
    if meta:
        lines.append(f"**{meta}**")
        lines.append("")
    followers = profile.get("follower_count", 0)
    connections = profile.get("connections_count", 0)
    fmt_n = lambda n: f"{n:,}".replace(",", " ") if n else "indisponible"
    lines.append(f"- **Abonnés** : {fmt_n(followers)}")
    lines.append(f"- **Connexions** : {fmt_n(connections)}")
    if profile:
        lines.append(f"- **Mode créateur** : {'oui' if profile.get('creator_mode') else 'non'}")
        lines.append(f"- **Badge influenceur** : {'oui' if profile.get('influencer') else 'non'}")
    cadence = f"{stats['posts_per_week']} posts/semaine" if stats.get("posts_per_week") is not None else "indisponible (dates non fournies)"
    lines.append(f"- **Cadence** : {cadence}")
    eng = stats.get("engagement", {})
    if eng.get("engagement_rate_pct") is not None:
        lines.append(
            f"- **Taux d'engagement médian** : {eng['engagement_rate_pct']}% "
            f"(commentaires : {eng['comments_rate_pct']}%)"
        )
    if eng.get("organic_rate_pct") is not None:
        lines.append(
            f"- **Taux organique médian** (likes + partages, hors commentaires « commente pour recevoir ») : {eng['organic_rate_pct']}%"
        )
    lines.append("")

    lines.append("## Positionnement")
    lines.append("")
    lines.append(f"**Positionnement** : {synthesis['positioning']}")
    lines.append("")
    lines.append(f"**Audience** : {synthesis['audience']}")
    lines.append("")

    # ========== Fréquence & timing (uniquement si les dates sont exploitables) ==========
    weekday_dist = stats.get("weekday_distribution") or {}
    if weekday_dist:
        lines.append("## Fréquence & timing")
        lines.append("")
        if stats.get("first_post_date") and stats.get("last_post_date"):
            lines.append(
                f"_Période analysée_ : {stats['first_post_date'][:10]} → {stats['last_post_date'][:10]} "
                f"({stats.get('dated_count', 0)} posts datés sur {stats['count']})"
            )
            lines.append("")
        weekdays_order = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        max_day = max(weekday_dist.values())
        lines.append("**Jours de publication**")
        lines.append("")
        lines.append("| Jour | Posts | |")
        lines.append("|---|---|---|")
        for day in weekdays_order:
            n = weekday_dist.get(day, 0)
            lines.append(f"| {day} | {n} | {_bar(n, max_day)} |")
        lines.append("")
        hour_dist = stats.get("hour_distribution") or {}
        if hour_dist:
            max_hour = max(hour_dist.values())
            lines.append("**Heures de publication** (heure de Paris)")
            lines.append("")
            lines.append("| Heure | Posts | |")
            lines.append("|---|---|---|")
            for hour in sorted(hour_dist, key=int):
                n = hour_dist[hour]
                lines.append(f"| {int(hour):02d}h | {n} | {_bar(n, max_hour)} |")
            lines.append("")

    lines.append("## Mix de formats")
    lines.append("")
    lines.append("| Format | % | Nb posts |")
    lines.append("|---|---|---|")
    for fmt, pct in sorted(stats["format_mix_pct"].items(), key=lambda x: -x[1]):
        n = stats["format_counts"].get(fmt, 0)
        lines.append(f"| {_format_label(fmt)} | {pct}% | {n} |")
    lines.append("")

    lines.append("## Répartition du contenu — attirer, éduquer, convertir")
    lines.append("")
    lines.append("**Attraction** _(TOFU)_ : contenu pour toucher de nouvelles audiences — storytelling, opinions, posts viraux, prises de position, sujets larges.")
    lines.append("")
    lines.append("**Éducation** _(MOFU)_ : contenu qui démontre l'expertise — méthodes, tutoriels, cas d'usage, frameworks qui font comprendre le problème et la solution.")
    lines.append("")
    lines.append("**Conversion** _(BOFU)_ : contenu qui vend — preuves, offres, témoignages, posts orientés prise de contact ou rendez-vous.")
    lines.append("")
    if classifications:
        stage_eng = {row["stage"]: row for row in stats.get("stage_engagement") or []}
        lines.append("| Étape | % | Nb posts | Engagement médian |")
        lines.append("|---|---|---|---|")
        for stage in ["TOFU", "MOFU", "BOFU"]:
            n = stage_dist.get(stage, 0)
            pct = round((n / total_class) * 100, 1)
            med = stage_eng.get(stage, {}).get("median_engagement")
            lines.append(f"| {_stage_label(stage)} | {pct}% | {n} | {med if med is not None else '–'} |")
        lines.append("")

        lines.append("**Types d'accroches** (la première ligne du post, celle qui arrête le scroll)")
        lines.append("")
        hook_eng = {row["hook_type"]: row for row in stats.get("hook_engagement") or []}
        if hook_eng:
            lines.append("| Accroche | Nb posts | Engagement médian | Record |")
            lines.append("|---|---|---|---|")
            for hook, n in sorted(hook_dist.items(), key=lambda x: -x[1]):
                row = hook_eng.get(hook, {})
                lines.append(
                    f"| {_hook_label(hook)} | {n} | {row.get('median_engagement', '–')} | {row.get('max_engagement', '–')} |"
                )
            lines.append("")
        else:
            for hook, n in sorted(hook_dist.items(), key=lambda x: -x[1]):
                lines.append(f"- {_hook_label(hook)} : {n}")
            lines.append("")
    else:
        lines.append("_Classification indisponible pour cette analyse._")
        lines.append("")

    lines.append("## Engagement")
    lines.append("")
    eng = stats["engagement"]
    lines.append(f"- **Likes médian / moyen** : {eng['median_likes']} / {eng['mean_likes']}")
    lines.append(f"- **Commentaires médian / moyen** : {eng['median_comments']} / {eng['mean_comments']}")
    lines.append(f"- **Partages médian / moyen** : {eng.get('median_reposts', '–')} / {eng['mean_reposts']}")
    lines.append(f"- **Engagement total médian** : {eng.get('median_engagement', '–')}")
    if eng.get("median_organic") is not None:
        lines.append(f"- **Engagement organique médian** (likes + partages) : {eng['median_organic']}")
    lines.append(f"- **Longueur médiane** : {stats['length']['median_words']} mots")
    lines.append("")

    # ========== BLOC 2 : Top 5 posts par engagement ==========
    top5 = stats.get("top_posts") or stats.get("top_posts_by_comments", [])
    if top5:
        has_cta_by_url = {
            p.get("url"): p.get("has_cta", False)
            for p in (patterns.get("posts_enriched") or [])
            if p.get("url")
        }
        lines.append("## Top 5 posts (par engagement total)")
        lines.append("")
        for i, p in enumerate(top5, 1):
            # " ".join(split()) neutralise TOUT retour à la ligne (\n, \r, U+2028…)
            # qui casserait le markdown
            txt = " ".join((p["text"] or "").split()).replace("[", "(").replace("]", ")")
            snippet = (txt[:110] + "…") if len(txt) > 110 else txt
            title = f"[{snippet}]({p['url']})" if p.get("url") else snippet
            cta = " · ✅ appel à commenter" if has_cta_by_url.get(p.get("url")) else ""
            lines.append(f"{i}. **{title}**  ")
            lines.append(
                f"   _{_format_label(p['format'])}_ — 👍 {p['likes']} · 💬 {p['comments']} · 🔁 {p['reposts']} · **{p['engagement']} interactions**{cta}"
            )
        lines.append("")
        lines.append("_Clique sur un extrait pour ouvrir le post sur LinkedIn. ✅ = les commentaires sont en partie mécaniques (« commente X pour recevoir »)._")
        lines.append("")

    # ========== BLOC 3 : Patterns détectés (déterministes) ==========
    if patterns:
        lines.append("## Récurrences détectées")
        lines.append("")

        len_d = patterns.get("length_distribution", {})
        if len_d:
            lines.append("**Longueur des posts**")
            for k in ["court", "moyen", "long"]:
                if k in len_d:
                    lines.append(f"- `{k}` : {len_d[k]}")
            lines.append("")

        sigs = patterns.get("visual_signatures", [])
        if sigs:
            lines.append("**Signatures visuelles récurrentes**")
            for sym, n in sigs:
                lines.append(f"- `{sym}` apparaît dans {n} posts")
            lines.append("")

        sections = patterns.get("recurring_sections", [])
        if sections:
            lines.append("**Sections / formules récurrentes**")
            for s, n in sections:
                lines.append(f"- *{s}* — {n} occurrences")
            lines.append("")

        cta_share = patterns.get("cta_share_pct", 0)
        cta_count = patterns.get("cta_count", 0)
        cta_kws = patterns.get("cta_keywords", [])
        lines.append("**Appels à commenter** _(CTA)_ — « commente X pour recevoir… »")
        lines.append(f"- {cta_count} posts avec appel explicite ({cta_share}% du total)")
        if cta_kws:
            kw_str = ", ".join(f"`{kw}` ({n})" for kw, n in cta_kws[:8])
            lines.append(f"- Mots-clés demandés en commentaire : {kw_str}")
        lines.append("")

        if cta_stats:
            wc = cta_stats.get("with_cta", {})
            wo = cta_stats.get("without_cta", {})
            if wc.get("count") and wo.get("count"):
                lines.append("**Effet de l'appel à commenter (médianes)**")
                lines.append("")
                lines.append("| | Avec appel | Sans appel |")
                lines.append("|---|---|---|")
                lines.append(f"| Posts | {wc['count']} | {wo['count']} |")
                lines.append(f"| Likes médian | {wc['median_likes']} | {wo['median_likes']} |")
                lines.append(f"| Commentaires médian | {wc['median_comments']} | {wo['median_comments']} |")
                lines.append(f"| Partages médian | {wc['median_reposts']} | {wo['median_reposts']} |")
                lines.append("")

    lines.append("## Analyse stratégique")
    lines.append("")
    lines.append("### Piliers de contenu")
    for pillar in synthesis["content_pillars"]:
        lines.append(f"- {pillar}")
    lines.append("")
    lines.append("### Accroches qui reviennent")
    for h in synthesis["hook_patterns"]:
        lines.append(f"- {h}")
    lines.append("")
    lines.append("### Structures récurrentes")
    for s in synthesis["structural_patterns"]:
        lines.append(f"- {s}")
    lines.append("")
    lines.append(f"**Stratégie d'appel à l'action** : {synthesis['cta_strategy']}")
    lines.append("")

    lines.append("## Forces")
    for s in synthesis["strengths"]:
        lines.append(f"- {s}")
    lines.append("")

    lines.append("## Manques / opportunités")
    for g in synthesis["gaps"]:
        lines.append(f"- {g}")
    lines.append("")

    lines.append("## ✨ Actions à répliquer")
    lines.append("")
    for i, a in enumerate(synthesis["actions_to_replicate"], 1):
        lines.append(f"{i}. {a}")
    lines.append("")

    # Usage & coûts : volontairement absents du rapport (version client).
    # Les données restent disponibles dans result["usage"] et la colonne `usage` en base.

    return "\n".join(lines)


def save_report(handle: str, content: str) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    path = REPORTS_DIR / f"{handle}-{ts}.md"
    path.write_text(content, encoding="utf-8")
    return path
