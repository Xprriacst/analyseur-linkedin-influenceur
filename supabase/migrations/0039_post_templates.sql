-- 0039 — Banque de templates de posts (ALE-216, tranche 1 d'ALE-208)
-- Un template = une structure de post réutilisable + un type d'image d'exemple.
-- Rempli à la main (source 'user') ou depuis la veille (source 'influencer', ALE-217).

create table if not exists public.post_templates (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  structure_label text not null,
  structure_text text not null,
  format text,
  image_url text,
  image_note text,
  source text not null default 'user',
  source_author text,
  source_post_url text,
  created_at timestamptz not null default now()
);

create index if not exists idx_post_templates_user
  on public.post_templates(user_id, created_at desc);

alter table public.post_templates enable row level security;

grant select, insert, update, delete on public.post_templates to authenticated;

drop policy if exists "users_own_post_templates" on public.post_templates;
create policy "users_own_post_templates"
  on public.post_templates
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Le Générateur passe par la file de jobs : le template choisi voyage avec le job.
alter table public.generation_jobs
  add column if not exists template_id uuid references public.post_templates(id) on delete set null;
