"""Normalize the various Apify actor schemas into a consistent post shape."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

# urn:li:activity:7457316472336371712 ou .../activity-7457316472336371712-xxxx
_ACTIVITY_ID_RE = re.compile(r"activity[:-](\d{15,25})")


def _get(d: dict, *keys, default=None):
    """Get a key from a dict. Supports dotted paths like 'engagement.likes'."""
    for k in keys:
        if "." in k:
            cur: Any = d
            ok = True
            for part in k.split("."):
                if isinstance(cur, dict) and part in cur and cur[part] is not None:
                    cur = cur[part]
                else:
                    ok = False
                    break
            if ok:
                return cur
        elif k in d and d[k] is not None:
            return d[k]
    return default


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _sane(dt: datetime | None) -> datetime | None:
    """Reject garbage dates (epochs mal interprétés, ex. 1781-07-12)."""
    if dt is None:
        return None
    if dt.year < 2005 or dt.year > datetime.now(timezone.utc).year + 1:
        return None
    return dt


def _from_epoch(value: float) -> datetime | None:
    # Heuristique : au-delà de 1e11 c'est des millisecondes (1e11 s ≈ année 5138)
    if value > 1e11:
        value = value / 1000.0
    try:
        return _sane(datetime.fromtimestamp(value, tz=timezone.utc))
    except (OverflowError, OSError, ValueError):
        return None


def _parse_date(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _sane(value)
    if isinstance(value, (int, float)):
        return _from_epoch(float(value))
    s = str(value).strip()
    if re.fullmatch(r"\d{10,17}(\.\d+)?", s):
        return _from_epoch(float(s))
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return _sane(datetime.strptime(s, fmt))
        except ValueError:
            continue
    try:
        return _sane(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        return None


def _date_from_urn(post: dict) -> datetime | None:
    """Fallback : l'ID d'activité LinkedIn encode la date (41 bits de poids fort = epoch ms)."""
    candidates = [
        _get(post, "full_urn", "urn.activity_urn", "activityUrn", "entityId", "id"),
        _get(post, "url", "postUrl", "linkedinUrl", "link"),
    ]
    for cand in candidates:
        if not cand:
            continue
        s = str(cand)
        m = _ACTIVITY_ID_RE.search(s)
        digits = m.group(1) if m else (s if s.isdigit() and 15 <= len(s) <= 25 else None)
        if digits:
            dt = _from_epoch(float(int(digits) >> 22))
            if dt:
                return dt
    return None


def _detect_format(post: dict) -> str:
    if _get(post, "isRepost", "reposted", default=False) or post.get("repost") or post.get("reshared_post"):
        return "repost"
    # Schéma apimaestro : media = {"type": "image|video|...", "images": [...]}
    media = post.get("media")
    if isinstance(media, dict):
        mtype = str(media.get("type") or "").lower()
        images = media.get("images") or []
        if mtype == "image":
            return "carousel" if isinstance(images, list) and len(images) > 1 else "image"
        if mtype in ("carousel", "slideshow"):
            return "carousel"
        if mtype:
            return mtype  # video, document, article, poll…
    if _get(post, "video", "videoUrl", "linkedinVideo"):
        return "video"
    images = _get(post, "images", "imageUrls", "postImages", default=[]) or []
    if isinstance(images, list) and len(images) > 1:
        return "carousel"
    if images:
        return "image"
    if _get(post, "article", "articleUrl"):
        return "article"
    if _get(post, "document", "documentUrl"):
        return "document"
    return "text"


def _extract_media(post: dict) -> list[dict]:
    """URLs des médias du post — {type, url}, dédupliquées (ALE-214, prérequis ALE-208).

    Jusqu'ici ces URLs n'étaient lues que pour deviner le format puis jetées ;
    on les conserve pour la veille et la banque de templates.
    """
    items: list[dict] = []

    def _push(kind: str, value: Any) -> None:
        url = value.get("url") if isinstance(value, dict) else value
        if isinstance(url, str) and url.startswith("http"):
            items.append({"type": kind, "url": url})

    # Schéma apimaestro : media = {"type": ..., "images": [...], "thumbnail": ..., "video_url"/"url": ...}
    media = post.get("media")
    if isinstance(media, dict):
        mtype = str(media.get("type") or "").lower()
        for img in media.get("images") or []:
            _push("image", img)
        if mtype == "video":
            _push("video", media.get("video_url") or media.get("url"))
            _push("image", media.get("thumbnail"))
        elif not items:
            _push("image", media.get("thumbnail"))
    # Schéma apimaestro post-detail : media = liste déjà typée [{"type": ..., "url": ...}].
    elif isinstance(media, list):
        for entry in media:
            if not isinstance(entry, dict):
                continue
            kind = str(entry.get("type") or "image").lower()
            if "video" in kind:
                _push("video", entry.get("url"))
                _push("image", entry.get("thumbnail"))
            else:
                _push("image", entry.get("url"))
    # Schémas harvestapi et variantes : listes d'images à plat.
    for key in ("images", "imageUrls", "postImages"):
        value = post.get(key)
        if isinstance(value, list):
            for img in value:
                _push("image", img)

    seen: set[str] = set()
    deduped = []
    for item in items:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        deduped.append(item)
    return deduped[:10]


# Alias public : utilisé hors normalisation (import d'un post isolé, ALE-222).
extract_media = _extract_media


def normalize_posts(raw: list[dict]) -> list[dict]:
    out = []
    for p in raw:
        text = _get(p, "text", "postText", "content", "commentary", default="") or ""
        # Les dates ISO d'abord, les timestamps epoch ensuite, l'URN en dernier recours.
        date = _parse_date(
            _get(
                p,
                "postedAt.date", "posted_at.date",
                "postedAt.timestamp", "posted_at.timestamp",
                "postedAt", "publishedAt", "date", "time", "postedAtTimestamp",
            )
        )
        if date is None:
            date = _date_from_urn(p)
        posted_ago = _get(p, "postedAt.postedAgoText", "postedAgoText", "posted_at.relative", default="") or ""
        # total_reactions avant stats.like : "like" exclut love/support/celebrate/insight
        likes = _safe_int(_get(p, "engagement.likes", "numLikes", "stats.total_reactions", "likes", "likeCount", "reactions", "stats.like", default=0))
        comments = _safe_int(_get(p, "engagement.comments", "numComments", "comments", "commentCount", "stats.comments", default=0))
        reposts = _safe_int(_get(p, "engagement.shares", "numShares", "shares", "reposts", "repostCount", "stats.reposts", default=0))
        url = _get(p, "url", "postUrl", "linkedinUrl", "link", default="")

        out.append(
            {
                "url": url,
                "text": text.strip(),
                "date": date,
                "posted_ago": posted_ago,
                "format": _detect_format(p),
                "likes": likes,
                "comments": comments,
                "reposts": reposts,
                "engagement": likes + comments + reposts,
                "length_chars": len(text),
                "length_words": len(text.split()),
                "media_items": _extract_media(p),
            }
        )
    out = [p for p in out if p["text"] or p["format"] != "text"]
    return out


def _avatar_url(raw: dict) -> str:
    """Photo de profil, tous schémas confondus (chaîne vide si absente).

    harvestapi range l'URL dans `pictureUrl` sous forme de dict par taille
    ({"100x100": …, "400x400": …}) ; apimaestro la met à plat sous basic_info.
    """
    bi = raw.get("basic_info") if isinstance(raw.get("basic_info"), dict) else {}
    for candidate in (
        bi.get("profile_picture_url"),
        bi.get("profile_picture"),
        raw.get("pictureUrl"),
        raw.get("profilePicture"),
        raw.get("photo"),
        raw.get("profilePic"),
    ):
        if isinstance(candidate, dict):
            for size in ("400x400", "200x200", "800x800", "100x100"):
                if candidate.get(size):
                    return str(candidate[size])
            for val in candidate.values():
                if val:
                    return str(val)
        elif candidate:
            return str(candidate)
    return ""


def _image_url(candidate: Any) -> str:
    """URL d'image, que le scraper la donne à plat ou en dict par taille."""
    if isinstance(candidate, dict):
        # harvestapi : {"url": …} ou {"sizes": [{"width":…, "url":…}, …]}
        if candidate.get("url"):
            return str(candidate["url"])
        sizes = candidate.get("sizes")
        if isinstance(sizes, list) and sizes:
            best = max(
                (s for s in sizes if isinstance(s, dict) and s.get("url")),
                key=lambda s: int(s.get("width") or 0),
                default=None,
            )
            if best:
                return str(best["url"])
        for val in candidate.values():
            if isinstance(val, str) and val.startswith("http"):
                return val
    elif isinstance(candidate, str) and candidate:
        return candidate
    return ""


def _banner_url(raw: dict) -> str:
    """Bannière (image de couverture) du profil, chaîne vide si absente.

    ⚠️ Une chaîne vide veut dire « pas de bannière personnalisée » : LinkedIn
    n'expose pas d'URL pour le fond bleu par défaut. C'est exactement le fait
    dont l'audit SEO a besoin — ne pas confondre avec un échec de scrape.
    """
    bi = raw.get("basic_info") if isinstance(raw.get("basic_info"), dict) else {}
    for candidate in (
        bi.get("background_picture_url"),
        raw.get("coverPicture"),
        raw.get("backgroundImage"),
        raw.get("backgroundPicture"),
    ):
        url = _image_url(candidate)
        if url:
            return url
    return ""


def _skills(raw: dict) -> list[str]:
    """Compétences déclarées, dans l'ordre du profil (les 1res comptent le plus)."""
    bi = raw.get("basic_info") if isinstance(raw.get("basic_info"), dict) else {}
    out: list[str] = []
    seen: set[str] = set()
    for source in (bi.get("top_skills"), raw.get("topSkills"), bi.get("skills"), raw.get("skills")):
        if not isinstance(source, list):
            continue
        for item in source:
            # apimaestro : liste de chaînes. harvestapi : liste de dicts {name, endorsements}.
            name = item if isinstance(item, str) else (item or {}).get("name") if isinstance(item, dict) else None
            name = (name or "").strip()
            key = name.lower()
            if name and key not in seen:
                seen.add(key)
                out.append(name)
    return out[:30]


def _job_titles(raw: dict) -> list[str]:
    """Intitulés de postes (actuels et passés) — indexés par la recherche LinkedIn."""
    out: list[str] = []
    seen: set[str] = set()
    for source in (raw.get("currentPosition"), raw.get("experience")):
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, dict):
                continue
            title = (item.get("position") or item.get("title") or "").strip()
            key = title.lower()
            if title and key not in seen:
                seen.add(key)
                out.append(title)
    return out[:12]


def _seo_signals(raw: dict) -> dict:
    """Ce que la « bible LinkedIn » regarde, extrait de ce qu'on scrape DÉJÀ.

    ⚠️ Aucun appel réseau supplémentaire : ces champs étaient renvoyés par les
    deux acteurs Apify depuis toujours et jetés par la normalisation. Les
    remonter ne coûte pas un centime de scrape en plus.
    """
    bi = raw.get("basic_info") if isinstance(raw.get("basic_info"), dict) else {}
    totals = raw.get("sectionTotals") if isinstance(raw.get("sectionTotals"), dict) else {}
    recos = raw.get("receivedRecommendations")
    return {
        "banner_url": _banner_url(raw),
        "skills": _skills(raw),
        "job_titles": _job_titles(raw),
        "public_identifier": str(
            bi.get("public_identifier") or raw.get("publicIdentifier") or ""
        ),
        "recommendations_count": int(
            (totals.get("receivedRecommendations") if isinstance(totals.get("receivedRecommendations"), int) else None)
            or (len(recos) if isinstance(recos, list) else 0)
        ),
        "experience_count": int(totals.get("experience") or 0),
        "open_to_work": bool(bi.get("open_to_work") or raw.get("openToWork")),
        "premium": bool(bi.get("is_premium") or raw.get("premium")),
        "verified": bool(bi.get("is_verified") or raw.get("verified")),
    }


def normalize_profile(raw: dict | None) -> dict:
    """Normalize the profile-scraper output."""
    if not raw:
        return {}

    # Schéma apimaestro/linkedin-profile-detail : tout est sous basic_info
    if isinstance(raw.get("basic_info"), dict):
        bi = raw["basic_info"]
        loc = bi.get("location") or {}
        name = bi.get("fullname") or f"{bi.get('first_name') or ''} {bi.get('last_name') or ''}".strip()
        return {
            "name": name,
            "headline": bi.get("headline") or "",
            "summary": bi.get("about") or "",
            "location": (loc.get("full") if isinstance(loc, dict) else str(loc)) or "",
            "follower_count": int(bi.get("follower_count") or 0),
            "connections_count": int(bi.get("connection_count") or 0),
            "creator_mode": bool(bi.get("is_creator")),
            "influencer": bool(bi.get("is_influencer")),
            "profile_url": bi.get("profile_url") or "",
            "avatar_url": _avatar_url(raw),
            "seo": _seo_signals(raw),
        }

    first = _get(raw, "firstName", "first_name", default="") or ""
    last = _get(raw, "lastName", "last_name", default="") or ""
    name = _get(raw, "fullName", "name", "displayName", default="") or f"{first} {last}".strip()
    return {
        "name": name,
        "headline": _get(raw, "headline", default=""),
        "summary": _get(raw, "summary", "about", default=""),
        "location": _get(raw, "geoLocationName", "location.linkedinText", "locationName", default="") or "",
        "follower_count": int(_get(raw, "followerCount", "followers", default=0) or 0),
        "connections_count": int(_get(raw, "connectionsCount", "connections", default=0) or 0),
        "creator_mode": bool(_get(raw, "creator", default=False)),
        "influencer": bool(_get(raw, "influencer", default=False)),
        "profile_url": _get(raw, "url", "profileUrl", "linkedinUrl", default=""),
        "avatar_url": _avatar_url(raw),
        "seo": _seo_signals(raw),
    }
