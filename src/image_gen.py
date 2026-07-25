"""Image generation for LinkedIn posts using GPT Image 2."""
from __future__ import annotations

import os
import random
import threading
import time

from anthropic import Anthropic
from openai import APIStatusError, OpenAI, RateLimitError

from src.net_guard import guarded_download

# Images de référence acceptées (banque de templates ALE-221, photos de soi 0054).
_REFERENCE_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp"}
_REFERENCE_IMAGE_CONTENT_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
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

# GPT Image 2 borne le nombre d'appels simultanés par org
# (« Error code: 503 - Too many concurrent requests »).
# On sérialise dans le process + on réessaie avec backoff.
_IMAGE_API_LOCK = threading.Lock()
_IMAGE_API_MAX_ATTEMPTS = 4  # 1 essai + 3 retries
_IMAGE_API_BASE_BACKOFF_S = 10.0


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
    return guarded_download(
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


def with_identity_prefix(prompt: str) -> str:
    """Préfixe d'identité — idempotent si déjà présent."""
    text = (prompt or "").strip()
    if not text:
        return _IDENTITY_PROMPT_PREFIX.strip()
    if text.startswith(_IDENTITY_PROMPT_PREFIX.strip()[:40]):
        return text
    return _IDENTITY_PROMPT_PREFIX + text


def _is_transient_openai_error(exc: BaseException) -> bool:
    """503 concurrent / 429 rate-limit — réessayables ; le reste non."""
    if "too many concurrent" in str(exc).lower():
        return True
    if isinstance(exc, RateLimitError):
        return True
    if isinstance(exc, APIStatusError) and getattr(exc, "status_code", None) in (429, 503):
        return True
    return False


def _friendly_openai_error(exc: Exception) -> ImageGenError:
    """Traduit 503/429 OpenAI en message actionnable."""
    raw = str(exc)
    low = raw.lower()
    if "too many concurrent" in low or (
        isinstance(exc, APIStatusError) and getattr(exc, "status_code", None) == 503
    ):
        return ImageGenError(
            "OpenAI est saturé (trop de générations d'images en parallèle). "
            "Réessaie dans une minute."
        )
    if isinstance(exc, RateLimitError) or "rate limit" in low:
        return ImageGenError(
            "Limite de débit OpenAI atteinte. Réessaie dans une minute."
        )
    return ImageGenError(f"Génération d'image refusée : {raw[:400]}")


def _call_openai_image_api(
    client: OpenAI,
    *,
    prompt: str,
    images: list[tuple[str, bytes, str]],
):
    """Appel OpenAI images.edit/generate avec verrou process + retries 503/429.

    Le verrou est gardé pendant l'attente de retry pour ne pas empiler
    d'autres appels pendant qu'on décharge la file concurrente OpenAI.
    """
    last_exc: Exception | None = None
    with _IMAGE_API_LOCK:
        for attempt in range(_IMAGE_API_MAX_ATTEMPTS):
            try:
                # Les modèles gpt-image-* renvoient toujours du b64_json
                # et n'acceptent pas quality="standard" (low/medium/high/auto).
                if images:
                    return client.images.edit(
                        model="gpt-image-2",
                        image=list(images),
                        prompt=prompt,
                        size="1024x1024",
                        quality="high",
                        output_format="png",
                        n=1,
                    )
                return client.images.generate(
                    model="gpt-image-2",
                    prompt=prompt,
                    size="1024x1024",
                    quality="high",
                    n=1,
                )
            except (RateLimitError, APIStatusError) as exc:
                last_exc = exc
                if not _is_transient_openai_error(exc) or attempt + 1 >= _IMAGE_API_MAX_ATTEMPTS:
                    raise _friendly_openai_error(exc) from exc
                delay = _IMAGE_API_BASE_BACKOFF_S * (2 ** attempt) + random.uniform(0, 3)
                print(
                    f"[image-gen] OpenAI saturé ({exc}), "
                    f"retry {attempt + 1}/{_IMAGE_API_MAX_ATTEMPTS - 1} dans {delay:.0f}s",
                    flush=True,
                )
                time.sleep(delay)
    raise _friendly_openai_error(last_exc or RuntimeError("Échec OpenAI image"))


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

    prompt = (prompt or "").strip() or build_image_prompt(post_text, identity=identity)
    if identity:
        prompt = with_identity_prefix(prompt)

    images: list[tuple[str, bytes, str]] = []
    if reference_images:
        images.extend(reference_images)
    elif reference_image:
        images.append(reference_image)

    client = OpenAI(api_key=api_key)
    response = _call_openai_image_api(client, prompt=prompt, images=images)
    b64 = response.data[0].b64_json
    return {
        "image_data": f"data:image/png;base64,{b64}",
        "prompt_used": prompt,
    }
