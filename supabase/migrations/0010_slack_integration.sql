-- Slack integration: connexion workspace Slack par utilisateur.
-- Permet d'envoyer des idées générées sur Slack pour validation (✅ / ❌).
--
-- `user_integrations` : une ligne par user et par service tiers.
--   Slack utilise service = 'slack', stocke le bot token + identifiants workspace.
-- `generated_ideas.slack_status` : suivi de la validation Slack (null → pending → validated/declined).
--
-- À exécuter manuellement dans le SQL editor Supabase (comme 0001 → 0009).

create table if not exists public.user_integrations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  service text not null,          -- 'slack'
  access_token text not null,     -- bot token (xoxb-...)
  service_user_id text,           -- Slack user ID (U0...)
  channel_id text,                -- DM channel ID (D0...) or chosen channel
  team_id text,                   -- Slack workspace ID (T0...)
  team_name text,                 -- Slack workspace name (display)
  metadata jsonb,
  connected_at timestamptz default now(),
  unique (user_id, service)
);

alter table public.generated_ideas
  add column if not exists slack_status text;  -- null | pending | validated | declined

create index if not exists idx_user_integrations_user
  on public.user_integrations(user_id, service);
create index if not exists idx_user_integrations_slack_user
  on public.user_integrations(service_user_id)
  where service = 'slack';

alter table public.user_integrations enable row level security;

grant select, insert, update, delete on public.user_integrations to authenticated;

drop policy if exists "users_own_integrations" on public.user_integrations;
create policy "users_own_integrations"
  on public.user_integrations
  for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
