-- 0038 — Monitoring influenceurs, brique 1 (ALE-214)
-- (1) Suivi par utilisateur : quels influenceurs surveiller (cap appliqué côté backend).
-- (2) Médias des posts scrapés : jusqu'ici lus pour deviner le format puis jetés —
--     on les conserve (prérequis ALE-208, banque de templates).
-- (3) Colonnes de suivi du cron : posts détectés automatiquement + relevé d'engagement
--     re-mesuré (l'engagement d'un post frais n'est pas stabilisé).

create table if not exists public.followed_influencers (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  handle text not null,
  platform text not null default 'linkedin',
  created_at timestamptz not null default now(),
  constraint followed_influencers_user_handle_unique unique (user_id, handle, platform)
);

create index if not exists idx_followed_influencers_user
  on public.followed_influencers(user_id);
create index if not exists idx_followed_influencers_handle
  on public.followed_influencers(handle, platform);

alter table public.followed_influencers enable row level security;

grant select, insert, update, delete on public.followed_influencers to authenticated;

drop policy if exists "users_own_followed_influencers" on public.followed_influencers;
create policy "users_own_followed_influencers"
  on public.followed_influencers
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Médias des posts (liste de {type, url}) — cache partagé + corpus utilisateur.
alter table public.cached_posts add column if not exists media_items jsonb;
alter table public.posts add column if not exists media_items jsonb;

-- Traçabilité du monitoring sur le cache partagé.
alter table public.cached_posts add column if not exists detected_by_monitor boolean not null default false;
alter table public.cached_posts add column if not exists engagement_checked_at timestamptz;
