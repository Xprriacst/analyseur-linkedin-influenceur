"""Image generation for LinkedIn posts using GPT Image 2."""
from __future__ import annotations

import io
import os

from anthropic import Anthropic
from openai import BadRequestError, OpenAI

from src.net_guard import guarded_download

# Images de référence acceptées (banque de templates ALE-221, photos de soi 0054).
_REFERENCE_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp"}
_REFERENCE_IMAGE_CONTENT_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
}
_EXT_TO_CONTENT_TYPE = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}
# Garde-fou taille : les images LinkedIn font quelques Mo max, large marge.
_MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024

# Préfixe injecté quand on génère à partir de photos de l'utilisateur : GPT Image 2
# reçoit les photos en entrée (images.edit) ET cette consigne d'identité dans le prompt.
_IDENTITY_PROMPT_PREFIX = (
    "Les images jointes sont des photos de la même personne. "
    "Préserve fidèlement son visage, sa coupe de cheveux, son teint et son apparence. "
    "Place cette personne dans le contexte décrit ci-dessous, style photoréaliste "
    "professionnel adapté à LinkedIn. Aucun texte, logo ni filigrane dans l'image.\n\n"
)


class ImageGenError(RuntimeError):
    """Levée quand la génération d'image ou la récupération de l'image de référence échoue."""


def build_image_prompt(post_text: str, *, identity: bool = False) -> str:
    """Use Claude to generate an image prompt from the post content.

    `identity=True` : le prompt place explicitement une personne (photos de soi)
    dans un contexte lié au post — au lieu d'une illustration générique.
    """
    from src.llm import thinking_kwargs

    client = Anthropic()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    if identity:
        system = (
            "You are an expert at writing prompts for AI image generation with a real person. "
            "Your goal: craft a concise, vivid image prompt (40–70 words) that places ONE person "
            "in a photorealistic professional LinkedIn scene matching the post. "
            "Rules: describe the SCENE and CONTEXT only (place, activity, lighting, framing) — "
            "never invent face/hair/clothing details (those come from reference photos). "
            "NO text or words in the image, square 1:1 format. "
            "Write the prompt in French. Reply with the prompt only — no explanation."
        )
    else:
        system = (
            "You are an expert at writing prompts for AI image generation. "
            "Your goal: craft a concise, vivid image prompt (30–50 words) "
            "for a professional LinkedIn post illustration. "
            "Rules: photorealistic style, NO text or words in the image, "
            "square 1:1 format, clean business/professional aesthetic. "
            # Le prompt est montré à l'utilisateur (pop-up ALE-68) avant génération :
            # il doit être rédigé en français pour qu'il puisse le relire/l'ajuster.
            "Write the prompt in French. "
            "Reply with the prompt only — no explanation."
        )
    msg = client.messages.create(
        model=model,
        max_tokens=180 if identity else 120,
        **thinking_kwargs(model),
        system=system,
        messages=[{"role": "user", "content": f"LinkedIn post:\n{post_text[:800]}"}],
    )
    return "".join(
        block.text for block in msg.content if getattr(block, "type", None) == "text"
    ).strip()


def fetch_reference_image(url: str, *, filename_stem: str = "reference") -> tuple[str, bytes, str]:
    """Télécharger une image de référence → (filename, bytes, content_type).

    Ces URLs viennent d'un champ libre côté client (saisie manuelle, post scrapé,
    ou photo de soi uploadée via Zernio) : traitées comme non fiables (garde-fou SSRF).
    """
    filename, data, content_type = guarded_download(
        url,
        allowed_exts=_REFERENCE_IMAGE_EXTS,
        default_ext="png",
        max_bytes=_MAX_REFERENCE_IMAGE_BYTES,
        allowed_hosts_env="IMAGE_REFERENCE_ALLOWED_HOSTS",
        content_type_ext_map=_REFERENCE_IMAGE_CONTENT_TYPES,
        error_cls=ImageGenError,
        filename_stem=filename_stem,
        user_agent="lkd-outreach/image-gen",
    )
    return normalize_reference_image((filename, data, content_type))


def with_identity_prefix(prompt: str) -> str:
    """Préfixe d'identité — idempotent si déjà présent."""
    text = (prompt or "").strip()
    if not text:
        return _IDENTITY_PROMPT_PREFIX.strip()
    if text.startswith(_IDENTITY_PROMPT_PREFIX.strip()[:40]):
        return text
    return _IDENTITY_PROMPT_PREFIX + text


def fallback_scene_prompt(post_text: str, *, identity: bool = False) -> str:
    """Scène minimale quand Claude ne renvoie rien — jamais un prompt vide.

    Un prompt vide est retiré du multipart par le SDK OpenAI → 400
    « No valid description provided » côté API (panne opaque pour l'utilisateur).
    """
    excerpt = " ".join((post_text or "").split())[:180]
    if identity:
        if excerpt:
            return (
                "Portrait professionnel de la personne dans un contexte LinkedIn "
                f"inspiré de ce sujet : {excerpt}. Lumière naturelle, cadrage mi-corps, "
                "ambiance de travail moderne."
            )
        return (
            "Portrait professionnel de la personne dans un bureau moderne lumineux, "
            "cadrage mi-corps, lumière naturelle, ambiance LinkedIn photoréaliste."
        )
    if excerpt:
        return (
            "Illustration photoréaliste professionnelle pour un post LinkedIn "
            f"sur : {excerpt}. Pas de texte dans l'image, format carré."
        )
    return (
        "Illustration photoréaliste professionnelle pour LinkedIn, "
        "ambiance bureau moderne, pas de texte, format carré."
    )


def normalize_reference_image(
    item: tuple[str, bytes, str],
) -> tuple[str, bytes, str]:
    """Force un Content-Type `image/*` fiable pour le multipart OpenAI.

    Les CDN (Zernio, etc.) renvoient parfois `application/octet-stream` : le SDK
    propage alors ce type dans la partie fichier, ce qui peut faire échouer
    `images.edit` de façon opaque. On dérive le type de l'extension du fichier.
    """
    filename, data, content_type = item
    if not data:
        raise ImageGenError("Image de référence vide.")
    stem, _, ext = filename.rpartition(".")
    ext = ext.lower()
    if ext not in _EXT_TO_CONTENT_TYPE:
        ext = "png"
        filename = f"{stem or 'reference'}.{ext}"
    expected = _EXT_TO_CONTENT_TYPE[ext]
    ct = (content_type or "").lower().split(";", 1)[0].strip()
    if ct == "image/jpg":
        ct = "image/jpeg"
    if ct not in _REFERENCE_IMAGE_CONTENT_TYPES:
        ct = expected
    return (filename, data, ct)


def to_openai_image_file(
    item: tuple[str, bytes, str],
) -> tuple[str, io.BytesIO, str]:
    """Convertit (filename, bytes, content_type) au format fichier attendu par le SDK."""
    filename, data, content_type = normalize_reference_image(item)
    return (filename, io.BytesIO(data), content_type)


def resolve_image_prompt(
    post_text: str,
    prompt: str | None = None,
    *,
    identity: bool = False,
) -> str:
    """Construit un prompt non vide prêt pour l'API Images OpenAI."""
    text = (prompt or "").strip()
    if not text:
        try:
            text = (build_image_prompt(post_text, identity=identity) or "").strip()
        except Exception:
            text = ""
    if not text:
        text = fallback_scene_prompt(post_text, identity=identity)
    if identity:
        text = with_identity_prefix(text)
    # Le préfixe seul (sans scène) ne décrit pas l'image → OpenAI peut le rejeter.
    # Si on n'a que le préfixe, on ajoute une scène de repli.
    if identity and text.strip() == _IDENTITY_PROMPT_PREFIX.strip():
        text = with_identity_prefix(fallback_scene_prompt(post_text, identity=True))
    if not text.strip():
        raise ImageGenError(
            "Aucun prompt d'image valide. Saisis une description de scène "
            "(lieu, activité, lumière) puis réessaie."
        )
    return text


def _friendly_openai_error(exc: Exception) -> ImageGenError:
    """Traduit les 400 OpenAI cryptiques en message actionnable."""
    raw = str(exc)
    low = raw.lower()
    if "no valid description" in low or "valid description provided" in low:
        return ImageGenError(
            "OpenAI a refusé le prompt (« aucune description valide »). "
            "Réécris une scène concrète (lieu, activité, lumière) — pas seulement "
            "« mets-moi dans l'image » — puis réessaie."
        )
    if "invalid" in low and "image" in low:
        return ImageGenError(
            "OpenAI a refusé une image de référence (format ou fichier illisible). "
            "Réessaie avec une photo JPG/PNG/WebP claire."
        )
    return ImageGenError(f"Génération d'image refusée : {raw[:400]}")


def generate_post_image(
    post_text: str,
    prompt: str | None = None,
    reference_image: tuple[str, bytes, str] | None = None,
    reference_images: list[tuple[str, bytes, str]] | None = None,
    identity: bool = False,
) -> dict:
    """Generate an image to accompany a LinkedIn post.

    `prompt` : prompt validé/édité par l'utilisateur ; s'il est vide, un prompt
    est construit automatiquement depuis le texte du post.
    `reference_image` : une image (rétro-compat ALE-221, style/composition).
    `reference_images` : plusieurs images (photos de soi) — bascule sur
    `images.edit` avec toutes les références.
    `identity` : préfixe le prompt pour verrouiller le visage de la personne.
    Returns {"image_data": "data:image/png;base64,...", "prompt_used": str}.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY manquant")

    prompt = resolve_image_prompt(post_text, prompt, identity=identity)

    images: list[tuple[str, bytes, str]] = []
    if reference_images:
        images.extend(reference_images)
    elif reference_image:
        images.append(reference_image)

    openai_files = [to_openai_image_file(img) for img in images]

    client = OpenAI(api_key=api_key)
    # Les modèles gpt-image-* renvoient toujours du b64_json (pas de response_format)
    # et n'acceptent pas quality="standard" (valeurs : low/medium/high/auto).
    try:
        if openai_files:
            response = client.images.edit(
                model="gpt-image-2",
                image=openai_files,
                prompt=prompt,
                size="1024x1024",
                quality="high",
                output_format="png",
                n=1,
            )
        else:
            response = client.images.generate(
                model="gpt-image-2",
                prompt=prompt,
                size="1024x1024",
                quality="high",
                n=1,
            )
    except BadRequestError as exc:
        raise _friendly_openai_error(exc) from exc
    b64 = response.data[0].b64_json
    return {
        "image_data": f"data:image/png;base64,{b64}",
        "prompt_used": prompt,
    }
