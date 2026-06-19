-- Idée du jour : réservoir d'idées rempli par le client + idée générée chaque
-- matin par le cron (`src/daily_ideas.py`).
--
-- `idea_seeds` : pile d'idées sources, alimentée/supprimée par le client (RLS user).
-- `daily_ideas` : une idée générée par jour et par utilisateur. Écriture réservée
--   au cron (service_role, qui bypass la RLS) → la policy `authenticated` n'autorise
--   que la lecture. Contrainte unique (user_id, idea_date) = garde-fou anti-doublon
--   si le cron repasse dans la journée.
-- `daily_ideas_enabled` : opt-in par client (switch « Recevoir une idée chaque matin »).
--
-- À exécuter manuellement dans le SQL editor Supabase (comme 0001 → 0006).

create table if not exists public.idea_seeds (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  text text not null,
  used_at timestamptz,
  created_at timestamptz default now()
);

create table if not exists public.daily_ideas (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  idea_date date not null default current_date,
  idea_markdown text not null,
  seed_id uuid references public.idea_seeds(id) on delete set null,
  created_at timestamptz default now(),
  unique (user_id, idea_date)
);

alter table public.user_editorial_profiles
  add column if not exists daily_ideas_enabled boolean default false;

create index if not exists idx_idea_seeds_user
  on public.idea_seeds(user_id, used_at);
create index if not exists idx_daily_ideas_user
  on public.daily_ideas(user_id, idea_date desc);

alter table public.idea_seeds enable row level security;
alter table public.daily_ideas enable row level security;

grant select, insert, update, delete on public.idea_seeds to authenticated;
-- daily_ideas en lecture seule côté client : seul le cron (service_role) écrit.
grant select on public.daily_ideas to authenticated;

drop policy if exists "users_own_seeds" on public.idea_seeds;
create policy "users_own_seeds"
  on public.idea_seeds
  for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists "users_read_daily" on public.daily_ideas;
create policy "users_read_daily"
  on public.daily_ideas
  for select
  to authenticated
  using ((select auth.uid()) = user_id);
