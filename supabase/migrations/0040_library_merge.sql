-- 0040 — « Ma bibliothèque » : fusion posts de référence + templates (ALE-222)
-- La table post_templates devient le stock unique (elle garde la FK
-- generation_jobs.template_id et le flux image de référence ALE-221).
-- Les posts de référence (ALE-67) y sont copiés ; user_reference_posts est
-- gelée (drop dans une migration ultérieure, après validation prod).
-- Idempotente : rejouable sans effet (notamment après déploiement, pour
-- rattraper les lignes écrites dans user_reference_posts entre l'application
-- de la migration et la mise en ligne du nouveau code).

-- Une entrée peut désormais n'être qu'un post (texte) sans structure.
alter table public.post_templates
  add column if not exists post_text text;
alter table public.post_templates
  add column if not exists note text;
alter table public.post_templates
  alter column structure_label drop not null;
alter table public.post_templates
  alter column structure_text drop not null;

-- Garde-fou : une entrée vide (ni texte ni structure) n'a pas de sens.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'post_templates_has_content'
      and conrelid = 'public.post_templates'::regclass
  ) then
    alter table public.post_templates
      add constraint post_templates_has_content
      check (post_text is not null or structure_text is not null);
  end if;
end $$;

-- Copie des posts de référence existants, clé primaire reportée pour
-- l'idempotence (on conflict do nothing).
insert into public.post_templates
  (id, user_id, post_text, note, source_author, source_post_url, source, created_at)
select id, user_id, text, note, author, url, 'user', created_at
from public.user_reference_posts
on conflict (id) do nothing;
