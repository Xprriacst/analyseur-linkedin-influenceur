"""Markdown report rendering."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote


REPORTS_DIR = Path("reports")


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

    lines: list[str] = []
    lines.append(f"# Stratégie LinkedIn — `{unquote(handle)}`")
    lines.append("")
    lines.append(f"_Profil_ : {profile_url}  ")
    lines.append(f"_Analyse générée le_ : {datetime.now().strftime('%Y-%m-%d %H:%M')}  ")
    excluded = stats.get("excluded_recent_count", 0)
    suffix = f" (— {excluded} post(s) <24h exclus)" if excluded else ""
    span = f"sur {stats['span_days']} jours" if stats.get("span_days") else "(dates indisponibles)"
    lines.append(f"_Posts analysés_ : **{stats['count']}** {span}{suffix}")
    lines.append("")

    # ========== BLOC 1 : Profil en chiffres ==========
    if profile:
        lines.append("## Profil en chiffres")
        lines.append("")
        name = profile.get("name") or handle
        headline = profile.get("headline") or ""
        location = profile.get("location") or ""
        meta = " · ".join(filter(None, [name, headline, location]))
        if meta:
            lines.append(f"**{meta}**")
            lines.append("")
        followers = profile.get("follower_count", 0)
        connections = profile.get("connections_count", 0)
        creator = "oui" if profile.get("creator_mode") else "non"
        influencer = "oui" if profile.get("influencer") else "non"
        lines.append(f"- **Abonnés** : {followers:,}".replace(",", " "))
        lines.append(f"- **Connexions** : {connections:,}".replace(",", " "))
        lines.append(f"- **Mode créateur** : {creator}")
        lines.append(f"- **Badge influenceur** : {influencer}")
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
                f"- **Taux organique médian** (likes + reposts, hors commentaires CTA) : {eng['organic_rate_pct']}%"
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
    lines.append("| Format | % | Nb |")
    lines.append("|---|---|---|")
    for fmt, pct in sorted(stats["format_mix_pct"].items(), key=lambda x: -x[1]):
        n = stats["format_counts"].get(fmt, 0)
        lines.append(f"| {fmt} | {pct}% | {n} |")
    lines.append("")

    lines.append("## Mix funnel TOFU / MOFU / BOFU")
    lines.append("")
    lines.append("**TOFU** (*Top of Funnel*) : contenu d'attraction — storytelling, opinions, posts viraux, prises de position, sujets larges pour toucher de nouvelles audiences.")
    lines.append("")
    lines.append("**MOFU** (*Middle of Funnel*) : contenu d'éducation — méthodes, frameworks, tutoriels, cas d'usage, expertise qui fait comprendre le problème et la solution.")
    lines.append("")
    lines.append("**BOFU** (*Bottom of Funnel*) : contenu de conversion — preuves, offres, CTA commerciaux, témoignages, posts orientés vente ou prise de rendez-vous.")
    lines.append("")
    if classifications:
        stage_eng = {row["stage"]: row for row in stats.get("stage_engagement") or []}
        lines.append("| Stage | % | Nb | Engagement médian |")
        lines.append("|---|---|---|---|")
        for stage in ["TOFU", "MOFU", "BOFU"]:
            n = stage_dist.get(stage, 0)
            pct = round((n / total_class) * 100, 1)
            med = stage_eng.get(stage, {}).get("median_engagement")
            lines.append(f"| {stage} | {pct}% | {n} | {med if med is not None else '–'} |")
        lines.append("")

        lines.append("**Types de hooks (classification LLM)**")
        lines.append("")
        hook_eng = {row["hook_type"]: row for row in stats.get("hook_engagement") or []}
        if hook_eng:
            lines.append("| Hook | Nb | Engagement médian | Max |")
            lines.append("|---|---|---|---|")
            for hook, n in sorted(hook_dist.items(), key=lambda x: -x[1]):
                row = hook_eng.get(hook, {})
                lines.append(
                    f"| `{hook}` | {n} | {row.get('median_engagement', '–')} | {row.get('max_engagement', '–')} |"
                )
            lines.append("")
        else:
            for hook, n in sorted(hook_dist.items(), key=lambda x: -x[1]):
                lines.append(f"- `{hook}` : {n}")
            lines.append("")
    else:
        lines.append("_Classification LLM désactivée._")
        lines.append("")

    lines.append("## Engagement")
    lines.append("")
    eng = stats["engagement"]
    lines.append(f"- **Likes médian / moyen** : {eng['median_likes']} / {eng['mean_likes']}")
    lines.append(f"- **Comments médian / moyen** : {eng['median_comments']} / {eng['mean_comments']}")
    lines.append(f"- **Reposts médian / moyen** : {eng.get('median_reposts', '–')} / {eng['mean_reposts']}")
    lines.append(f"- **Engagement total médian** : {eng.get('median_engagement', '–')}")
    if eng.get("median_organic") is not None:
        lines.append(f"- **Engagement organique médian** (likes + reposts) : {eng['median_organic']}")
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
        lines.append("| # | Format | Sujet (extrait) | Likes | Comments | Shares | Eng. | CTA |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for i, p in enumerate(top5, 1):
            txt = p["text"].replace("\n", " ").replace("|", "/")
            snippet = (txt[:90] + "…") if len(txt) > 90 else txt
            cta = "✅" if has_cta_by_url.get(p.get("url")) else "—"
            lines.append(
                f"| {i} | {p['format']} | {snippet} | {p['likes']} | {p['comments']} | {p['reposts']} | {p['engagement']} | {cta} |"
            )
        lines.append("")
        lines.append("_CTA ✅ = post avec appel à commenter (« commente X pour recevoir ») : les commentaires y sont en partie mécaniques._")
        lines.append("")
        for i, p in enumerate(top5, 1):
            if p.get("url"):
                lines.append(f"{i}. <{p['url']}>")
        lines.append("")

    # ========== BLOC 3 : Patterns détectés (déterministes) ==========
    if patterns:
        lines.append("## Patterns structurels (détectés)")
        lines.append("")

        hook_d = patterns.get("hook_distribution", {})
        if hook_d:
            lines.append("**Types de hooks (heuristique 1ère ligne — peut différer de la classification LLM ci-dessus)**")
            for h, n in sorted(hook_d.items(), key=lambda x: -x[1]):
                lines.append(f"- `{h}` : {n}")
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
        lines.append("**CTA commentaires**")
        lines.append(f"- {cta_count} posts avec CTA explicite ({cta_share}% du total)")
        if cta_kws:
            kw_str = ", ".join(f"`{kw}` ({n})" for kw, n in cta_kws[:8])
            lines.append(f"- Mots-clés détectés : {kw_str}")
        lines.append("")

        if cta_stats:
            wc = cta_stats.get("with_cta", {})
            wo = cta_stats.get("without_cta", {})
            if wc.get("count") and wo.get("count"):
                lines.append("**Effet du CTA (médianes)**")
                lines.append("")
                lines.append("| | Avec CTA | Sans CTA |")
                lines.append("|---|---|---|")
                lines.append(f"| Posts | {wc['count']} | {wo['count']} |")
                lines.append(f"| Likes médian | {wc['median_likes']} | {wo['median_likes']} |")
                lines.append(f"| Comments médian | {wc['median_comments']} | {wo['median_comments']} |")
                lines.append(f"| Reposts médian | {wc['median_reposts']} | {wo['median_reposts']} |")
                lines.append("")

    lines.append("## Patterns (synthèse LLM)")
    lines.append("")
    lines.append("### Piliers de contenu")
    for pillar in synthesis["content_pillars"]:
        lines.append(f"- {pillar}")
    lines.append("")
    lines.append("### Hooks récurrents")
    for h in synthesis["hook_patterns"]:
        lines.append(f"- {h}")
    lines.append("")
    lines.append("### Patterns structurels")
    for s in synthesis["structural_patterns"]:
        lines.append(f"- {s}")
    lines.append("")
    lines.append(f"**Stratégie de CTA** : {synthesis['cta_strategy']}")
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

    if usage:
        apify = usage.get("apify", {})
        anthropic = usage.get("anthropic", {})
        total_cost = round(
            float(apify.get("estimated_cost_usd", 0) or 0)
            + float(anthropic.get("estimated_cost_usd", 0) or 0),
            6,
        )
        lines.append("## Usage & coûts estimés")
        lines.append("")
        lines.append(f"- **Apify** : {apify.get('runs', 0)} run(s), {apify.get('cached_runs', 0)} cache hit(s), {apify.get('items', 0)} item(s), ~${apify.get('estimated_cost_usd', 0)}")
        lines.append(f"- **Anthropic** : {anthropic.get('calls', 0)} appel(s), {anthropic.get('input_tokens', 0)} input tokens, {anthropic.get('output_tokens', 0)} output tokens, ~${anthropic.get('estimated_cost_usd', 0)}")
        lines.append(f"- **Total estimé** : ~${total_cost}")
        lines.append("")

    return "\n".join(lines)


def save_report(handle: str, content: str) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    path = REPORTS_DIR / f"{handle}-{ts}.md"
    path.write_text(content, encoding="utf-8")
    return path
