-- File d'attente serveur pour la génération de posts (ALE-141).
-- À exécuter dans le SQL editor du projet Supabase zcxaxwqkswuefzlzpgvi.
--
-- Contrairement aux analyses (série multi-profils → 2 tables), une génération est
-- une requête unique (un sujet → N variants). Une seule table suffit : une ligne
-- = un job de génération, dont le résultat (variants) est stocké en jsonb une fois
-- terminé. L'état vit en base → le frontend peut quitter la page et revenir, le
-- résultat est conservé.
--
-- RLS : chaque utilisateur ne voit/écrit que ses propres jobs (auth.uid() = user_id).

create table if not exists public.generation_jobs (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references auth.users(id) on delete cascade,
  status          text not null default 'queued',  -- queued | running | done | error | cancelled
  topic           text,
  editorial_role  text,
  web_search      boolean not null default false,
  count           int not null default 1,
  result          jsonb,   -- {variants:[...], save_error, web_search:{...}} une fois `done`
  error           text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists idx_generation_jobs_user_created
  on public.generation_jobs(user_id, created_at desc);

alter table public.generation_jobs enable row level security;

drop policy if exists "own_generation_jobs" on public.generation_jobs;

create policy "own_generation_jobs" on public.generation_jobs
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
