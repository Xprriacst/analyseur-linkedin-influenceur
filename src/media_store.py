"""Stockage durable des images applicatives.

Zernio sert très bien de pipeline média pour la PUBLICATION, mais ses uploads
présignés vivent d'abord en stockage temporaire (`/temp/`) et expirent si aucun
post publié ne les "matérialise". Pour les images que l'app doit relire des
jours ou des semaines plus tard (photos de soi, bibliothèque, veille), on les
stocke donc dans Supabase Storage.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import time
from typing import Any

from src import db
from src.net_guard import guarded_download

BUCKET = "app-media"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "gif"}
_DATA_URL_RE = re.compile(r"^data:(?P<content_type>[-\w.]+/[-+\w.]+);base64,(?P<data>.+)$", re.DOTALL)


class MediaStoreError(RuntimeError):
    """Levée quand une image durable ne peut pas être écrite ou relue."""


def enabled() -> bool:
    return db.admin_enabled()


def _sanitize_filename(filename: str | None, default_ext: str) -> str:
    name = (filename or "").strip().split("/")[-1].split("\\")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    if not name:
        name = f"image.{default_ext}"
    if "." not in name:
        name = f"{name}.{default_ext}"
    return name[:120]


def _storage_path(*, scope: str, filename: str, data: bytes) -> str:
    stamp = int(time.time() * 1000)
    digest = hashlib.sha1(data).hexdigest()[:12]
    return f"{scope}/{stamp}_{digest}_{filename}"


def _upload_bytes(*, data: bytes, content_type: str, filename: str, scope: str) -> str:
    if not enabled():
        raise MediaStoreError("SUPABASE_SERVICE_ROLE_KEY manquant : stockage média durable indisponible.")
    safe_name = _sanitize_filename(filename, IMAGE_CONTENT_TYPES.get(content_type, "png"))
    path = _storage_path(scope=scope, filename=safe_name, data=data)
    try:
        bucket = db.admin_client().storage.from_(BUCKET)
        bucket.upload(
            path=path,
            file=data,
            file_options={
                "content-type": content_type,
                "cache-control": "31536000",
                "upsert": "false",
            },
        )
        return bucket.get_public_url(path)
    except Exception as exc:  # noqa: BLE001 - remonte un message métier court
        raise MediaStoreError(f"Upload Storage échoué : {exc}") from exc


def upload_image_data_url(data_url: str, *, filename: str | None = None, scope: str = "self-photos") -> str:
    """Data URL image → URL publique stable Supabase Storage."""
    match = _DATA_URL_RE.match((data_url or "").strip())
    if not match:
        raise MediaStoreError("Image invalide : format data URL base64 attendu.")
    content_type = match.group("content_type").lower()
    if content_type not in IMAGE_CONTENT_TYPES:
        raise MediaStoreError("Format image non supporté. Utilise JPG, PNG, WebP ou GIF.")
    try:
        data = base64.b64decode(match.group("data"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MediaStoreError("Image invalide : base64 illisible.") from exc
    if not data:
        raise MediaStoreError("Image invalide : fichier vide.")
    if len(data) > MAX_IMAGE_BYTES:
        raise MediaStoreError("Image trop volumineuse (10 Mo maximum).")
    return _upload_bytes(
        data=data,
        content_type=content_type,
        filename=filename or "image.png",
        scope=scope,
    )


def rehost_external_image(url: str, *, filename_stem: str = "image", scope: str = "library") -> str:
    """Télécharge une image tierce publique puis la stocke durablement.

    Les URLs de CDN LinkedIn, de sites tiers, ou de stockages temporaires ne
    doivent jamais être persistées telles quelles quand l'app compte les relire
    plus tard.
    """
    filename, data, content_type = guarded_download(
        url,
        allowed_exts=IMAGE_EXTS,
        default_ext="png",
        max_bytes=MAX_IMAGE_BYTES,
        allowed_hosts_env="IMAGE_REFERENCE_ALLOWED_HOSTS",
        content_type_ext_map=IMAGE_CONTENT_TYPES,
        error_cls=MediaStoreError,
        filename_stem=filename_stem,
        user_agent="lkd-outreach/media-store",
    )
    return _upload_bytes(data=data, content_type=content_type, filename=filename, scope=scope)


def rehost_image_media_items(
    media_items: list[dict[str, Any]] | None,
    *,
    scope: str,
) -> list[dict[str, Any]] | None:
    """Réhéberge les images d'une liste `media_items`; garde le reste intact."""
    if not media_items:
        return media_items
    out: list[dict[str, Any]] = []
    for index, item in enumerate(media_items, start=1):
        entry = dict(item or {})
        url = str(entry.get("url") or "").strip()
        if entry.get("type") == "image" and url:
            try:
                entry["url"] = rehost_external_image(
                    url,
                    filename_stem=f"{scope}-{index}",
                    scope=scope,
                )
            except MediaStoreError:
                continue
        out.append(entry)
    return out


def is_durable_url(url: str | None) -> bool:
    """Vrai si l'URL pointe déjà sur notre stockage durable."""
    text = (url or "").strip().lower()
    return f"/storage/v1/object/public/{BUCKET}/" in text


def persist_image_attachments(
    images: list[dict[str, Any]] | None,
    *,
    scope: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Images jointes par le client → `media_items` à URLs durables.

    C'est le point d'entrée de TOUT ce que l'app doit relire plus tard (idée du
    réservoir, post sauvegardé, post programmé, message Slack de validation) :
    une image déposée aujourd'hui est relue des jours après, elle ne peut donc
    pas vivre dans le `/temp/` de Zernio.

    Retourne `(items, degraded)`. `degraded` signale une image qu'on n'a pas su
    rendre durable — le front doit le dire plutôt que d'afficher une vignette
    qui cassera. Lève `MediaStoreError` seulement quand une image que le client
    vient d'uploader ne peut pas être stockée du tout (là, il faut le lui dire).
    """
    if not images:
        return [], False
    out: list[dict[str, Any]] = []
    degraded = False
    for index, image in enumerate(images, start=1):
        entry = dict(image or {})
        source = str(entry.get("data_url") or entry.get("url") or "").strip()
        if not source:
            raise MediaStoreError("Image invalide : URL ou data_url manquante.")
        stem = f"{scope}-{index}"
        if source.startswith("data:"):
            # Octets fournis par le client : un échec ici est une vraie panne,
            # on ne fait pas semblant d'avoir enregistré sa photo.
            url = upload_image_data_url(source, filename=entry.get("filename") or f"{stem}.png", scope=scope)
        elif is_durable_url(source):
            url = source
        else:
            try:
                url = rehost_external_image(source, filename_stem=stem, scope=scope)
            except MediaStoreError:
                degraded = True
                if db.looks_temporary_media_url(source):
                    # Connue pour expirer : la persister serait reproduire le bug.
                    continue
                # URL tierce (CDN d'une annonce) : rien ne dit qu'elle expire, et
                # la jeter perdrait la photo à coup sûr. On la garde, signalée.
                url = source
        item: dict[str, Any] = {"type": "image", "url": url}
        title = str(entry.get("title") or entry.get("filename") or "").strip()
        if title:
            item["title"] = title[:200]
        out.append(item)
    return out, degraded
