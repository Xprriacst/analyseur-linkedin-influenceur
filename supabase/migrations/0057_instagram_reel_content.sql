-- ALE-291 : Contenu Instagram aligné sur LinkedIn — parcours guidé (pack Reel).
--
-- Réutilise les tables existantes (generation_jobs, idea_seeds, generated_posts)
-- plutôt que d'en créer des jumelles : une colonne `platform` les scope par
-- réseau. Décision actée avec Alex : le réservoir d'idées reste SÉPARÉ par
-- réseau (`idea_seeds.platform`) pour éviter la pollution cross-plateforme déjà
-- vécue sur ALE-126/ALE-127 — filtrer, jamais partager, entre LinkedIn et
-- Instagram.
--
-- `ig_trame_id` porte la trame de reel choisie (storytelling, tuto, liste…) —
-- catalogue statique côté code, pas une table (pas de bibliothèque de
-- structures Instagram pour l'instant, contrairement à `post_templates` côté
-- LinkedIn).
--
-- `reel_details` porte le pack complet (hook, script, hashtags) d'un post
-- Instagram sauvegardé ; `generated_posts.post` continue de porter le texte
-- principal affiché en premier (la caption, pour Instagram).
--
-- Idempotente (rejouable).

alter table public.generation_jobs
  add column if not exists platform text not null default 'linkedin',
  add column if not exists ig_trame_id text;

do $$ begin
  if not exists (
    select 1 from pg_constraint where conname = 'generation_jobs_platform_check'
  ) then
    alter table public.generation_jobs
      add constraint generation_jobs_platform_check check (platform in ('linkedin', 'instagram'));
  end if;
end $$;

alter table public.idea_seeds
  add column if not exists platform text not null default 'linkedin';

do $$ begin
  if not exists (
    select 1 from pg_constraint where conname = 'idea_seeds_platform_check'
  ) then
    alter table public.idea_seeds
      add constraint idea_seeds_platform_check check (platform in ('linkedin', 'instagram'));
  end if;
end $$;

alter table public.generated_posts
  add column if not exists platform text not null default 'linkedin',
  add column if not exists reel_details jsonb;

do $$ begin
  if not exists (
    select 1 from pg_constraint where conname = 'generated_posts_platform_check'
  ) then
    alter table public.generated_posts
      add constraint generated_posts_platform_check check (platform in ('linkedin', 'instagram'));
  end if;
end $$;

comment on column public.generation_jobs.ig_trame_id is
  'ALE-291 — trame de reel choisie (catalogue statique côté code : storytelling, tuto, liste…).';
comment on column public.generated_posts.reel_details is
  'ALE-291 — pack Instagram sauvegardé : {hook, script, hashtags}. `post` porte la caption.';
