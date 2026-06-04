"""CLI entrypoint: analyze a LinkedIn profile's posting strategy."""
from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv
from rich.console import Console

from src.scraper import extract_handle, fetch_posts, fetch_profile
from src.normalize import normalize_posts, normalize_profile
from src.stats import compute_stats, cta_breakdown
from src.patterns import analyze_patterns
from src.llm import classify_posts, synthesize_strategy
from src.report import render_markdown, save_report
from src.usage import get_usage, reset_usage


def main() -> int:
    load_dotenv()
    reset_usage()
    console = Console()

    parser = argparse.ArgumentParser(description="Decode a LinkedIn influencer's strategy.")
    parser.add_argument("profile_url", help="https://linkedin.com/in/<handle>")
    parser.add_argument("--limit", type=int, default=30, help="Number of posts to fetch")
    parser.add_argument("--no-cache", action="store_true", help="Force re-scrape")
    args = parser.parse_args()

    handle = extract_handle(args.profile_url)

    with console.status(f"[bold cyan]Scraping profil @{handle}…"):
        raw_profile = fetch_profile(args.profile_url, use_cache=not args.no_cache)
    profile = normalize_profile(raw_profile)
    if profile.get("follower_count"):
        console.log(f"✓ Profil : {profile.get('name') or handle} — {profile['follower_count']:,} abonnés".replace(",", " "))
    else:
        console.log("⚠ Profil non récupéré (continue sans)")

    with console.status(f"[bold cyan]Scraping posts de @{handle}…"):
        raw = fetch_posts(args.profile_url, limit=args.limit, use_cache=not args.no_cache)
    console.log(f"✓ {len(raw)} posts récupérés")

    posts = normalize_posts(raw)
    if not posts:
        console.print("[red]Aucun post exploitable.")
        return 1
    console.log(f"✓ {len(posts)} posts normalisés")

    with console.status("[bold cyan]Calcul des stats…"):
        stats = compute_stats(posts, profile=profile)
    cadence = stats["posts_per_week"] if stats["posts_per_week"] is not None else "n/a"
    console.log(
        f"✓ Stats : {cadence} posts/sem, "
        f"comments médian={stats['engagement']['median_comments']}"
    )

    with console.status("[bold cyan]Détection patterns (CTA, hooks, signatures)…"):
        patterns = analyze_patterns(posts)
        cta_stats = cta_breakdown(patterns["posts_enriched"])
    console.log(
        f"✓ Patterns : {patterns['cta_count']} posts avec CTA "
        f"({patterns['cta_share_pct']}%)"
    )

    with console.status("[bold cyan]Classification TOFU/MOFU/BOFU via LLM…"):
        classifications = classify_posts(posts)
    console.log(f"✓ {len(classifications)} posts classés")

    with console.status("[bold cyan]Synthèse stratégique…"):
        synthesis = synthesize_strategy(stats, classifications, posts)
    console.log("✓ Synthèse générée")

    usage = get_usage()
    md = render_markdown(
        handle,
        args.profile_url,
        stats,
        classifications,
        synthesis,
        posts,
        profile=profile,
        patterns=patterns,
        cta_stats=cta_stats,
        usage=usage,
    )
    path = save_report(handle, md)
    total_cost = (
        usage["apify"]["estimated_cost_usd"]
        + usage["anthropic"]["estimated_cost_usd"]
    )
    console.log(
        f"✓ Usage : Apify {usage['apify']['items']} items, "
        f"Anthropic {usage['anthropic']['input_tokens'] + usage['anthropic']['output_tokens']} tokens, "
        f"~${total_cost:.4f}"
    )
    console.print(f"\n[bold green]→ Rapport :[/] {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
