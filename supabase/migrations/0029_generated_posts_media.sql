-- Images sur les posts envoyés directement en validation Slack.
-- Symétrie avec scheduled_posts.media_items (0018) : on stocke les URLs
-- publiques (Zernio) des images jointes pour qu'elles s'affichent sur Slack et
-- survivent aux clics Valider/Modifier (qui rechargent le post depuis la base).
-- Idempotente, rétro-compatible (défaut = tableau vide).

alter table public.generated_posts
  add column if not exists media_items jsonb not null default '[]'::jsonb;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'generated_posts_media_items_is_array'
  ) then
    alter table public.generated_posts
      add constraint generated_posts_media_items_is_array
      check (jsonb_typeof(media_items) = 'array');
  end if;
end $$;
