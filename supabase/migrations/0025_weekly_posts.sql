-- [Posts hebdo] Socle DB de la feature « 3 posts/semaine » (ALE-159).
--
-- weekly_posts_enabled : opt-in par utilisateur (calqué sur daily_ideas_enabled).
-- weekly_post_schedule : jours/heures de publication configurables par client,
--   une ligne par (user_id, day_of_week). day_of_week : 0 = lundi … 6 = dimanche.
--   Valeurs par défaut : lundi/mercredi/vendredi à 9h, fuseau Europe/Paris.
--   Écriture session uniquement (l'UI configure, le cron lit avec le service-role).
--
-- À exécuter manuellement dans le SQL editor Supabase (base partagée prod/dev).

-- Opt-in hebdo sur le profil éditorial existant
alter table public.user_editorial_profiles
  add column if not exists weekly_posts_enabled boolean default false;

-- Planning configurable : un slot par (utilisateur, jour de semaine)
create table if not exists public.weekly_post_schedule (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  day_of_week smallint not null check (day_of_week between 0 and 6),
  hour        smallint not null default 9 check (hour between 0 and 23),
  timezone    text not null default 'Europe/Paris',
  created_at  timestamptz default now(),
  updated_at  timestamptz default now(),
  unique (user_id, day_of_week)
);

create index if not exists idx_weekly_post_schedule_user
  on public.weekly_post_schedule(user_id);

alter table public.weekly_post_schedule enable row level security;

grant select, insert, update, delete on public.weekly_post_schedule to authenticated;

drop policy if exists "users_own_weekly_schedule" on public.weekly_post_schedule;
create policy "users_own_weekly_schedule"
  on public.weekly_post_schedule
  for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
