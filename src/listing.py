"""Lire une annonce immobilière depuis son URL (ALE-156).

`fetch_listing_preview(url)` télécharge la page, en extrait l'image principale et
les infos du bien (titre, prix, surface, pièces, localisation, description), puis
renvoie de quoi générer un post LinkedIn ancré dessus + l'image rattachable.

V1 = module léger basé sur les balises OpenGraph (`og:*`) + JSON-LD. Valide sur
les sites d'agence/MLS classiques (ex. elliman.com). Les sites anti-bot type
StreetEasy (HTTP 403, PerimeterX) ne passent pas → `ListingError` clair, fallback
headless/Apify = ticket séparé.

Stdlib uniquement (urllib + re + json), pour rester aligné avec api.py/zernio.py.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from typing import Any

# Garde-fous image (alignés sur src/zernio.py — limites LinkedIn).
MAX_IMAGE_BYTES = 8 * 1024 * 1024
_ALLOWED_IMAGE_CT = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}
_EXT_TO_CT = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif",
}

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

_HTML_TIMEOUT = 20
_IMAGE_TIMEOUT = 20
_MAX_HTML_BYTES = 4 * 1024 * 1024  # une annonce dépasse rarement quelques centaines de Ko


class ListingError(RuntimeError):
    """L'annonce n'a pas pu être lue (site bloqué, pas d'image, URL invalide…)."""


# --- Garde-fou SSRF -------------------------------------------------------- #
# L'URL vient du client : c'est notre serveur qui va la chercher. Sans contrôle,
# on pourrait être poussé à requêter des cibles internes (localhost, IP privées,
# métadonnées cloud 169.254.169.254…). On n'autorise donc que du http(s) public
# et on revalide chaque redirection (file://, ftp://, gopher://… exclus de fait).

def _assert_public_http_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ListingError("Lien non supporté : seules les adresses http(s) sont autorisées.")
    host = parsed.hostname
    if not host:
        raise ListingError("Lien invalide : nom de domaine manquant.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ListingError(f"Annonce injoignable : domaine introuvable ({host}).") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ListingError("Lien refusé : il pointe vers une adresse interne ou privée.")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Revalide chaque saut de redirection (un site public peut rediriger vers une IP interne)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirectHandler)


def is_listing_url(text: str | None) -> bool:
    """Vrai si le texte est une URL http(s) seule (= un lien d'annonce collé)."""
    if not text:
        return False
    text = text.strip()
    if " " in text or "\n" in text:
        return False
    parsed = urllib.parse.urlparse(text)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _fetch_html(url: str) -> str:
    _assert_public_http_url(url)
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    try:
        with _OPENER.open(req, timeout=_HTML_TIMEOUT) as resp:
            raw = resp.read(_MAX_HTML_BYTES)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 429):
            raise ListingError(
                "Ce site bloque la lecture automatique des annonces (protection anti-robot). "
                "Essaie un lien d'un autre site, ou colle le texte de l'annonce à la main."
            ) from exc
        raise ListingError(f"L'annonce est inaccessible (erreur {exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise ListingError(f"Annonce injoignable : {exc.reason}.") from exc
    return raw.decode("utf-8", errors="ignore")


def _meta_content(html: str, prop: str) -> str | None:
    """Récupère le `content` d'une balise <meta property|name="prop">."""
    pattern_after = (
        r'<meta[^>]+(?:property|name)=["\']'
        + re.escape(prop)
        + r'["\'][^>]+content=["\']([^"\']*)["\']'
    )
    pattern_before = (
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']'
        + re.escape(prop)
        + r'["\']'
    )
    for pattern in (pattern_after, pattern_before):
        m = re.search(pattern, html, re.IGNORECASE)
        if m and m.group(1).strip():
            return unescape(m.group(1).strip())
    return None


def _iter_jsonld(html: str):
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        try:
            data = json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, list):
            yield from (d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            if isinstance(data.get("@graph"), list):
                yield from (d for d in data["@graph"] if isinstance(d, dict))
            else:
                yield data


def _first_img_src(html: str) -> str | None:
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _jsonld_image(node: dict[str, Any]) -> str | None:
    image = node.get("image")
    if isinstance(image, str):
        return image
    if isinstance(image, list) and image:
        first = image[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return first.get("url") or first.get("contentUrl")
    if isinstance(image, dict):
        return image.get("url") or image.get("contentUrl")
    return None


def _extract_listing_facts(html: str) -> dict[str, Any]:
    """Titre / description / prix / surface / pièces / localisation, best-effort."""
    facts: dict[str, Any] = {
        "title": _meta_content(html, "og:title"),
        "description": _meta_content(html, "og:description"),
        "price": None,
        "surface": None,
        "rooms": None,
        "location": None,
    }
    for node in _iter_jsonld(html):
        offers = node.get("offers")
        if isinstance(offers, dict) and offers.get("price") and not facts["price"]:
            currency = offers.get("priceCurrency") or ""
            facts["price"] = f"{offers['price']} {currency}".strip()
        elif node.get("price") and not facts["price"]:
            facts["price"] = str(node["price"])

        floor = node.get("floorSize")
        if isinstance(floor, dict) and floor.get("value") and not facts["surface"]:
            unit = floor.get("unitText") or floor.get("unitCode") or ""
            facts["surface"] = f"{floor['value']} {unit}".strip()

        if node.get("numberOfRooms") and not facts["rooms"]:
            rooms = node["numberOfRooms"]
            facts["rooms"] = str(rooms.get("value")) if isinstance(rooms, dict) else str(rooms)

        addr = node.get("address")
        if addr and not facts["location"]:
            if isinstance(addr, dict):
                parts = [
                    addr.get("streetAddress"),
                    addr.get("addressLocality"),
                    addr.get("postalCode"),
                    addr.get("addressRegion"),
                    addr.get("addressCountry"),
                ]
                facts["location"] = ", ".join(p for p in parts if isinstance(p, str) and p.strip())
            elif isinstance(addr, str):
                facts["location"] = addr
    return facts


def _download_image(image_url: str) -> tuple[str, bytes]:
    """Télécharge l'image, valide type (content-type OU extension) + taille."""
    _assert_public_http_url(image_url)
    req = urllib.request.Request(image_url, headers={"User-Agent": _BROWSER_HEADERS["User-Agent"]})
    try:
        with _OPENER.open(req, timeout=_IMAGE_TIMEOUT) as resp:
            data = resp.read(MAX_IMAGE_BYTES + 1)
            header_ct = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise ListingError(f"Image de l'annonce non téléchargeable : {exc}.") from exc

    if not data:
        raise ListingError("L'image de l'annonce est vide.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ListingError("L'image de l'annonce dépasse 8 Mo (limite LinkedIn).")

    content_type = header_ct if header_ct in _ALLOWED_IMAGE_CT else ""
    if not content_type:
        # Beaucoup de CDN renvoient application/octet-stream → on se rabat sur l'extension.
        ext = urllib.parse.urlparse(image_url).path.rsplit(".", 1)[-1].lower()
        content_type = _EXT_TO_CT.get(ext, "")
    if not content_type:
        raise ListingError("Format d'image non reconnu (JPG, PNG, WebP ou GIF attendu).")
    return content_type, data


def fetch_listing_preview(url: str, *, download_image: bool = True) -> dict[str, Any]:
    """Lit une annonce immobilière et renvoie image + infos du bien.

    Retour : `source_url`, `title`, `description`, `price`, `surface`, `rooms`,
    `location`, `image_url` (URL publique de la photo principale) et, si
    `download_image`, `image_data_url` (data URL base64 prête pour Zernio).

    Lève `ListingError` (message clair) si le site bloque ou s'il n'y a pas d'image.
    """
    if not is_listing_url(url):
        raise ListingError("Lien invalide : colle l'URL complète d'une annonce (https://…).")

    html = _fetch_html(url)

    image_url = _meta_content(html, "og:image")
    if not image_url:
        for node in _iter_jsonld(html):
            image_url = _jsonld_image(node)
            if image_url:
                break
    if not image_url:
        image_url = _first_img_src(html)
    if not image_url:
        raise ListingError("Pas de photo trouvée sur cette annonce (aucune image principale).")

    # URL relative → absolue, puis revalidée (l'og:image peut être n'importe quelle
    # URL absolue — y compris un scheme dangereux ou une cible interne).
    image_url = urllib.parse.urljoin(url, unescape(image_url.strip()))
    _assert_public_http_url(image_url)

    facts = _extract_listing_facts(html)
    preview: dict[str, Any] = {
        "source_url": url,
        "image_url": image_url,
        "image_data_url": None,
        **facts,
    }

    if download_image:
        content_type, data = _download_image(image_url)
        b64 = base64.b64encode(data).decode("ascii")
        preview["image_data_url"] = f"data:{content_type};base64,{b64}"
    return preview


def build_listing_topic(preview: dict[str, Any]) -> str:
    """Construit le « sujet » passé au générateur à partir des infos du bien."""
    lines = ["Rédige un post LinkedIn pour mettre en avant ce bien immobilier."]
    if preview.get("title"):
        lines.append(f"Bien : {preview['title']}.")
    details = []
    if preview.get("price"):
        details.append(f"prix {preview['price']}")
    if preview.get("surface"):
        details.append(f"surface {preview['surface']}")
    if preview.get("rooms"):
        details.append(f"{preview['rooms']} pièces")
    if preview.get("location"):
        details.append(f"situé à {preview['location']}")
    if details:
        lines.append("Caractéristiques : " + ", ".join(details) + ".")
    if preview.get("description"):
        lines.append(f"Description de l'annonce : {preview['description']}")
    lines.append(
        "Mets en valeur le bien et l'expertise de l'agent sans recopier l'annonce mot pour mot."
    )
    return "\n".join(lines)
