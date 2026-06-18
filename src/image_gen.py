"""Image generation for LinkedIn posts using GPT Image 2."""
from __future__ import annotations

import os

from anthropic import Anthropic
from openai import OpenAI


def _build_image_prompt(post_text: str) -> str:
    """Use Claude to generate an image prompt from the post content."""
    client = Anthropic()
    msg = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        max_tokens=120,
        system=(
            "You are an expert at writing prompts for AI image generation. "
            "Your goal: craft a concise, vivid image prompt (30–50 words) "
            "for a professional LinkedIn post illustration. "
            "Rules: photorealistic style, NO text or words in the image, "
            "square 1:1 format, clean business/professional aesthetic. "
            "Reply with the prompt only — no explanation."
        ),
        messages=[{"role": "user", "content": f"LinkedIn post:\n{post_text[:800]}"}],
    )
    return msg.content[0].text.strip()


def generate_post_image(post_text: str) -> dict:
    """Generate an image to accompany a LinkedIn post.

    Returns {"image_data": "data:image/png;base64,...", "prompt_used": str}.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY manquant")

    prompt = _build_image_prompt(post_text)

    client = OpenAI(api_key=api_key)
    response = client.images.generate(
        model="gpt-image-2",
        prompt=prompt,
        size="1024x1024",
        quality="standard",
        n=1,
        response_format="b64_json",
    )
    b64 = response.data[0].b64_json
    return {
        "image_data": f"data:image/png;base64,{b64}",
        "prompt_used": prompt,
    }
