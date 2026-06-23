-- ALE-68 : persistance de l'image générée par post.
-- Ajoute deux colonnes nullables sur generated_posts (idempotent).

alter table public.generated_posts
  add column if not exists image_data text,
  add column if not exists image_prompt text;
