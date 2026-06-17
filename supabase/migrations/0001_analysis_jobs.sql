-- File d'attente serveur pour les analyses groupées (backlog multi-profils).
-- À exécuter dans le SQL editor du projet Supabase zcxaxwqkswuefzlzpgvi.
--
-- Deux tables :
--   analysis_jobs       → une "série" (batch) soumise par un utilisateur
--   analysis_job_items  → une ligne par profil LinkedIn de la série, avec son statut
--
-- RLS : chaque utilisateur ne voit/écrit que ses propres jobs (auth.uid() = user_id).

create table if not exists public.analysis_jobs (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  status      text not null default 'queued',   -- queued | running | stalled | done | error | cancelled
  total       int  not null default 0,
  completed   int  not null default 0,
  failed      int  not null default 0,
  limit_posts int,
  run_llm     boolean not null default true,
  use_cache   boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table if not exists public.analysis_job_items (
  id             uuid primary key default gen_random_uuid(),
  job_id         uuid not null references public.analysis_jobs(id) on delete cascade,
  user_id        uuid not null references auth.users(id) on delete cascade,
  position       int  not null default 0,
  url            text not null,
  handle         text,
  name           text,
  status         text not null default 'pending', -- pending | running | done | error | cancelled
  error          text,
  analysis_id    uuid references public.analyses(id) on delete set null,
  influencer_id  uuid references public.influencers(id) on delete set null,
  follower_count int,
  posts_count    int,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists idx_job_items_job        on public.analysis_job_items(job_id);
create index if not exists idx_jobs_user_created    on public.analysis_jobs(user_id, created_at desc);

alter table public.analysis_jobs      enable row level security;
alter table public.analysis_job_items enable row level security;

drop policy if exists "own_jobs"      on public.analysis_jobs;
drop policy if exists "own_job_items" on public.analysis_job_items;

create policy "own_jobs" on public.analysis_jobs
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "own_job_items" on public.analysis_job_items
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
