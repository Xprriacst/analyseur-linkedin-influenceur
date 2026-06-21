"""Instagram Markdown report rendering."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path


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


def render_ig_markdown(
    handle: str,
    url: str,
    stats: dict,
    classifications: list[dict],
    synthesis: dict,
    posts: list[dict],
    profile: dict | None = None,
    patterns: dict | None = None,
    cta_stats: dict | None = None,
    usage: dict | None = None,
) -> str:
    """Render a Markdown analysis report for an Instagram profile."""
    stage_dist = _stage_distribution(classifications)
    hook_dist = _hook_distribution(classifications)
    total_class = sum(stage_dist.values()) or 1
    profile = profile or {}
    patterns = patterns or {}
    cta_stats = cta_stats or {}
    usage = usage or {}

    lines: list[str] = []
    name = profile.get("name") or handle
    lines.append(f"# Stratégie Instagram — {name}")
    lines.append("")
    lines.append(f"_Profil_ : {url}  ")
    lines.append(f"_Analyse générée le_ : {datetime.now().strftime('%Y-%m-%d %H:%M')}  ")
    excluded = stats.get("excluded_recent_count", 0)
    suffix = f" (— {excluded} reel(s) <24h exclus)" if excluded else ""
    lines.append(f"_Reels analysés_ : **{stats['count']}**{suffix}")
    lines.append("")

    # ========== BLOC 1 : Profil en chiffres ==========
    lines.append("## Profil en chiffres")
    lines.append("")
    headline = profile.get("headline") or profile.get("business_category") or ""
    meta = " · ".join(filter(None, [name, headline]))
    if meta:
        lines.append(f"**{meta}**")
        lines.append("")

    followers = profile.get("follower_count", 0) or 0
    following = profile.get("connections_count", 0) or 0
    posts_count = profile.get("posts_count", 0) or 0
    is_verified = profile.get("influencer", False)
    is_business = profile.get("is_business", False)

    lines.append(f"- **Abonnés** : {followers:,}".replace(",", " "))
    lines.append(f"- **Abonnements** : {following:,}".replace(",", " "))
    if posts_count:
        lines.append(f"- **Posts totaux** : {posts_count:,}".replace(",", " "))
    lines.append(f"- **Compte vérifié** : {'oui' if is_verified else 'non'}")
    if is_business:
        biz_cat = profile.get("business_category") or ""
        lines.append(f"- **Compte professionnel** : oui{(' (' + biz_cat + ')') if biz_cat else ''}")

    cadence = f"{stats['posts_per_week']} reels/semaine" if stats.get("posts_per_week") is not None else "indisponible (dates non fournies)"
    lines.append(f"- **Cadence** : {cadence}")

    eng = stats.get("engagement", {})
    if eng.get("engagement_rate_pct") is not None:
        lines.append(f"- **Taux d'engagement médian** : {eng['engagement_rate_pct']}%")
    if eng.get("virality_ratio") is not None:
        virality_pct = round(eng["virality_ratio"] * 100, 2)
        lines.append(f"- **Ratio viralité (vues/abonnés)** : {virality_pct}%")
    lines.append("")

    # ========== BLOC 2 : Métriques Instagram ==========
    lines.append("## Métriques Instagram")
    lines.append("")
    if eng.get("median_views") is not None:
        lines.append(f"- **Vues médian** : {eng['median_views']:,}".replace(",", " "))
    if eng.get("mean_views") is not None:
        lines.append(f"- **Vues moyen** : {round(eng['mean_views'], 0):,.0f}".replace(",", " "))
    if eng.get("median_likes") is not None:
        lines.append(f"- **Likes médian** : {eng['median_likes']:,}".replace(",", " "))
    if eng.get("median_comments") is not None:
        lines.append(f"- **Commentaires médian** : {eng['median_comments']:,}".replace(",", " "))
    if eng.get("median_engagement") is not None:
        lines.append(f"- **Engagement médian** : {eng['median_engagement']:,}".replace(",", " "))
    if eng.get("quality_ratio") is not None:
        quality_pct = round(eng["quality_ratio"] * 100, 2)
        lines.append(f"- **Ratio qualité (engagement/vues)** : {quality_pct}%")
    lines.append("")

    # ========== Video duration stats ==========
    video_dur = stats.get("video_duration")
    if video_dur:
        lines.append("## Durée des Reels")
        lines.append("")
        if video_dur.get("median_s") is not None:
            lines.append(f"- **Durée médiane** : {video_dur['median_s']}s")
        if video_dur.get("mean_s") is not None:
            lines.append(f"- **Durée moyenne** : {round(video_dur['mean_s'], 1)}s")
        dist = video_dur.get("distribution", {})
        if dist:
            lines.append("")
            lines.append("| Durée | Nb reels |")
            lines.append("|---|---|")
            for bucket, count in dist.items():
                lines.append(f"| {bucket} | {count} |")
        lines.append("")

    # ========== Positionnement (LLM) ==========
    lines.append("## Positionnement")
    lines.append("")
    lines.append(f"**Positionnement** : {synthesis.get('positioning', '—')}")
    lines.append("")
    lines.append(f"**Audience** : {synthesis.get('audience', '—')}")
    lines.append("")

    # ========== Fréquence & Timing ==========
    has_dates = bool(stats.get("weekday_distribution")) or bool(stats.get("hour_distribution"))
    if has_dates:
        lines.append("## Fréquence & Timing")
        lines.append("")
        lines.append(f"- **Rythme** : {cadence}")
        if stats.get("first_post_date"):
            lines.append(f"- **Premier reel analysé** : {stats['first_post_date'][:10]}")
        if stats.get("last_post_date"):
            lines.append(f"- **Dernier reel analysé** : {stats['last_post_date'][:10]}")
        lines.append("")

        weekday_dist = stats.get("weekday_distribution", {})
        if weekday_dist:
            lines.append("**Jours de publication**")
            lines.append("")
            lines.append("| Jour | Reels | |")
            lines.append("|---|---|---|")
            weekdays_order = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
            max_day = max(weekday_dist.values(), default=1)
            for d in weekdays_order:
                n = weekday_dist.get(d, 0)
                lines.append(f"| {d} | {n} | `{_bar(n, max_day)}` |")
            lines.append("")

        hour_dist = stats.get("hour_distribution", {})
        if hour_dist:
            lines.append("**Heures de publication**")
            lines.append("")
            max_hour = max(hour_dist.values())
            lines.append("| Heure | Reels | |")
            lines.append("|---|---|---|")
            for h in sorted(hour_dist.keys()):
                n = hour_dist[h]
                lines.append(f"| {h:02d}h | {n} | `{_bar(n, max_hour)}` |")
            lines.append("")

    # ========== Mix de formats ==========
    lines.append("## Mix de formats")
    lines.append("")
    lines.append("| Format | % | Nb |")
    lines.append("|---|---|---|")
    for fmt, pct in sorted(stats.get("format_mix_pct", {}).items(), key=lambda x: -x[1]):
        n = stats.get("format_counts", {}).get(fmt, 0)
        lines.append(f"| {fmt} | {pct}% | {n} |")
    lines.append("")

    # ========== Funnel Awareness / Engagement / Conversion ==========
    lines.append("## Répartition du contenu — Attirer, Engager, Convertir")
    lines.append("")
    lines.append("**Awareness** : contenu d'attraction — divertissement, stories, opinions, sujets larges pour toucher de nouvelles personnes.")
    lines.append("")
    lines.append("**Engagement** : contenu d'éducation — tutoriels, méthodes, cas concrets, expertise qui crée une relation durable.")
    lines.append("")
    lines.append("**Conversion** : contenu de conversion — preuves, offres, témoignages, CTA directs (DM, lien bio).")
    lines.append("")
    lines.append("| Stage | % | Nb |")
    lines.append("|---|---|---|")
    for stage in ["Awareness", "Engagement", "Conversion"]:
        n = stage_dist.get(stage, 0)
        pct = round((n / total_class) * 100, 1)
        lines.append(f"| {stage} | {pct}% | {n} |")
    lines.append("")

    if hook_dist:
        lines.append("**Types d'accroches**")
        lines.append("")
        for hook, n in sorted(hook_dist.items(), key=lambda x: -x[1]):
            lines.append(f"- `{hook}` : {n}")
        lines.append("")

    # ========== Top 5 Reels par vues ==========
    top5_views = stats.get("top_posts_by_views", [])
    if top5_views:
        lines.append("## Top 5 Reels (par vues)")
        lines.append("")
        lines.append("| # | Format | Sujet (extrait) | Vues | Likes | Commentaires |")
        lines.append("|---|---|---|---|---|---|")
        for i, p in enumerate(top5_views, 1):
            txt = (p.get("text") or "").replace("\n", " ").replace("|", "/")
            snippet = (txt[:80] + "…") if len(txt) > 80 else txt
            views = p.get("views", 0) or 0
            lines.append(f"| {i} | {p.get('format', '—')} | {snippet} | {views:,} | {p.get('likes', 0)} | {p.get('comments', 0)} |".replace(",", " "))
        lines.append("")
        for i, p in enumerate(top5_views, 1):
            if p.get("url"):
                lines.append(f"{i}. <{p['url']}>")
        lines.append("")

    # ========== Hashtag strategy ==========
    hashtag_strat = patterns.get("hashtag_strategy", {})
    if hashtag_strat:
        lines.append("## Stratégie Hashtags")
        lines.append("")
        lines.append(f"- **Posts avec hashtags** : {hashtag_strat.get('uses_hashtags_pct', 0)}%")
        lines.append(f"- **Nb médian de hashtags** : {hashtag_strat.get('count_median', 0)}")
        top_tags = hashtag_strat.get("top_hashtags", [])
        if top_tags:
            lines.append(f"- **Hashtags récurrents** : {', '.join('#' + t for t, _ in top_tags[:8])}")
        lines.append("")

    # ========== CTAs ==========
    cta_count = patterns.get("cta_count", 0)
    cta_share = patterns.get("cta_share_pct", 0)
    cta_kws = patterns.get("cta_keywords", [])
    lines.append("## Appels à l'action (CTA)")
    lines.append("")
    lines.append(f"- {cta_count} reels avec CTA détecté ({cta_share}% du total)")
    if cta_kws:
        kw_str = ", ".join(f"`{kw}` ({n})" for kw, n in cta_kws[:8])
        lines.append(f"- Types détectés : {kw_str}")
    lines.append("")

    if cta_stats:
        wc = cta_stats.get("with_cta", {})
        wo = cta_stats.get("without_cta", {})
        if wc.get("count") and wo.get("count"):
            lines.append("**Effet du CTA (médianes)**")
            lines.append("")
            lines.append("| | Avec CTA | Sans CTA |")
            lines.append("|---|---|---|")
            lines.append(f"| Reels | {wc['count']} | {wo['count']} |")
            lines.append(f"| Likes médian | {wc['median_likes']} | {wo['median_likes']} |")
            lines.append(f"| Commentaires médian | {wc['median_comments']} | {wo['median_comments']} |")
            lines.append(f"| Engagement médian | {wc['median_engagement']} | {wo['median_engagement']} |")
            lines.append("")

    # ========== Analyse stratégique (LLM) ==========
    lines.append("## Analyse stratégique")
    lines.append("")
    lines.append("### Piliers de contenu")
    for pillar in synthesis.get("content_pillars", []):
        lines.append(f"- {pillar}")
    lines.append("")
    lines.append("### Accroches récurrentes")
    for h in synthesis.get("hook_patterns", []):
        lines.append(f"- {h}")
    lines.append("")
    lines.append("### Patterns structurels")
    for s in synthesis.get("structural_patterns", []):
        lines.append(f"- {s}")
    lines.append("")
    cta_strat = synthesis.get("cta_strategy", "—")
    lines.append(f"**Stratégie de CTA** : {cta_strat}")
    lines.append("")

    lines.append("## Forces")
    for s in synthesis.get("strengths", []):
        lines.append(f"- {s}")
    lines.append("")

    lines.append("## Manques / opportunités")
    for g in synthesis.get("gaps", []):
        lines.append(f"- {g}")
    lines.append("")

    lines.append("## Actions à répliquer")
    lines.append("")
    for i, a in enumerate(synthesis.get("actions_to_replicate", []), 1):
        lines.append(f"{i}. {a}")
    lines.append("")

    return "\n".join(lines)


def save_ig_report(handle: str, content: str) -> Path:
    """Save an Instagram report to disk."""
    REPORTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    path = REPORTS_DIR / f"{handle}-ig-{ts}.md"
    path.write_text(content, encoding="utf-8")
    return path
