"""Image generation for LinkedIn posts using GPT Image 2."""
from __future__ import annotations

import os

from anthropic import Anthropic
from openai import OpenAI

from src.net_guard import guarded_download

# Images de référence acceptées (banque de templates, ALE-221).
_REFERENCE_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp"}
_REFERENCE_IMAGE_CONTENT_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
}
# Garde-fou taille : les images LinkedIn font quelques Mo max, large marge.
_MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024


class ImageGenError(RuntimeError):
    """Levée quand la génération d'image ou la récupération de l'image de référence échoue."""


def build_image_prompt(post_text: str) -> str:
    """Use Claude to generate an image prompt from the post content."""
    from src.llm import thinking_kwargs

    client = Anthropic()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    msg = client.messages.create(
        model=model,
        max_tokens=120,
        **thinking_kwargs(model),
        system=(
            "You are an expert at writing prompts for AI image generation. "
            "Your goal: craft a concise, vivid image prompt (30–50 words) "
            "for a professional LinkedIn post illustration. "
            "Rules: photorealistic style, NO text or words in the image, "
            "square 1:1 format, clean business/professional aesthetic. "
            # Le prompt est montré à l'utilisateur (pop-up ALE-68) avant génération :
            # il doit être rédigé en français pour qu'il puisse le relire/l'ajuster.
            "Write the prompt in French. "
            "Reply with the prompt only — no explanation."
        ),
        messages=[{"role": "user", "content": f"LinkedIn post:\n{post_text[:800]}"}],
    )
    return "".join(
        block.text for block in msg.content if getattr(block, "type", None) == "text"
    ).strip()


def fetch_reference_image(url: str) -> tuple[str, bytes, str]:
    """Télécharger une image de référence (banque de templates) → (filename, bytes, content_type).

    Ces URLs viennent d'un champ libre côté client (saisie manuelle ou
    récupérée d'un post scrapé) : traitées comme non fiables (garde-fou SSRF).
    """
    return guarded_download(
        url,
        allowed_exts=_REFERENCE_IMAGE_EXTS,
        default_ext="png",
        max_bytes=_MAX_REFERENCE_IMAGE_BYTES,
        allowed_hosts_env="IMAGE_REFERENCE_ALLOWED_HOSTS",
        content_type_ext_map=_REFERENCE_IMAGE_CONTENT_TYPES,
        error_cls=ImageGenError,
        filename_stem="reference",
        user_agent="lkd-outreach/image-gen",
    )


def generate_post_image(
    post_text: str,
    prompt: str | None = None,
    reference_image: tuple[str, bytes, str] | None = None,
) -> dict:
    """Generate an image to accompany a LinkedIn post.

    `prompt` : prompt validé/édité par l'utilisateur ; s'il est vide, un prompt
    est construit automatiquement depuis le texte du post.
    `reference_image` : (filename, bytes, content_type) d'une image de la
    banque de templates à utiliser comme référence de style/composition —
    bascule sur l'édition d'image plutôt que la génération pure.
    Returns {"image_data": "data:image/png;base64,...", "prompt_used": str}.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY manquant")

    prompt = (prompt or "").strip() or build_image_prompt(post_text)

    client = OpenAI(api_key=api_key)
    # Les modèles gpt-image-* renvoient toujours du b64_json (pas de response_format)
    # et n'acceptent pas quality="standard" (valeurs : low/medium/high/auto).
    if reference_image:
        filename, data, content_type = reference_image
        response = client.images.edit(
            model="gpt-image-2",
            image=[(filename, data, content_type)],
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
    b64 = response.data[0].b64_json
    return {
        "image_data": f"data:image/png;base64,{b64}",
        "prompt_used": prompt,
    }
