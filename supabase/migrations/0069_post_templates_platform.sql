-- 0069 — « Ma bibliothèque » : parité Instagram, lot 1 (import par lien + trames)
-- post_templates devient partagée entre LinkedIn et Instagram, distinguées par
-- une colonne `platform` (comme generated_posts.platform, 0057). Les entrées
-- existantes restent 'linkedin' (comportement inchangé). Idempotente.

alter table public.post_templates
  add column if not exists platform text not null default 'linkedin';

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'post_templates_platform_check'
      and conrelid = 'public.post_templates'::regclass
  ) then
    alter table public.post_templates
      add constraint post_templates_platform_check
      check (platform in ('linkedin', 'instagram'));
  end if;
end $$;

create index if not exists idx_post_templates_user_platform
  on public.post_templates(user_id, platform, created_at desc);
