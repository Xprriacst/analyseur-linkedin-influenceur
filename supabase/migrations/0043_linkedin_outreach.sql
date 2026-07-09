-- 0043 — Prospection LinkedIn, brique 4 (ALE-230, epic ALE-226)
-- Envoi via Unipile + garde-fous quota.
-- (1) `linkedin_outreach_accounts` : le compte LinkedIn de chaque client connecté
--     via Unipile (modèle multi-client, une ligne par utilisateur) + la config de
--     quota (plafond quotidien, plafond hebdo glissant d'invitations).
-- (2) `linkedin_outreach_actions` : journal des actions envoyées (invitation /
--     message). Les compteurs de quota se CALCULENT depuis ce journal sur des
--     fenêtres glissantes (24 h / 7 j) — pas de compteurs à réinitialiser par cron,
--     donc pas de bug de reset.
-- (3) colonnes d'état d'outreach sur `leads` : où en est chaque lead (invitation
--     envoyée → connecté → premier message envoyé) + son provider_id Unipile et
--     l'id de conversation.
-- Idempotente (IF NOT EXISTS). RLS auth.uid() = user_id.

-- 1. Compte Unipile connecté + config quota (une ligne par utilisateur).
create table if not exists public.linkedin_outreach_accounts (
  user_id             uuid primary key references auth.users(id) on delete cascade,
  unipile_account_id  text,                              -- id du compte LinkedIn côté Unipile
  account_name        text,                              -- nom LinkedIn affiché (best-effort)
  status              text not null default 'connected', -- connected | error
  -- Garde-fous quota (protègent le compte LinkedIn d'une restriction) :
  daily_cap           integer not null default 25,       -- plafond quotidien, appliqué SÉPARÉMENT aux invitations et aux messages
  weekly_invite_cap   integer not null default 100,      -- sécurité hebdo glissante sur les invitations
  connected_at        timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

alter table public.linkedin_outreach_accounts enable row level security;

grant select, insert, update, delete on public.linkedin_outreach_accounts to authenticated;

drop policy if exists "users_own_linkedin_outreach_accounts" on public.linkedin_outreach_accounts;
create policy "users_own_linkedin_outreach_accounts"
  on public.linkedin_outreach_accounts
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- 2. Journal des actions d'envoi (source des compteurs de quota).
create table if not exists public.linkedin_outreach_actions (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  lead_id      uuid references public.leads(id) on delete set null,
  action_type  text not null,                            -- invite | message
  status       text not null default 'sent',             -- sent | failed
  provider_id  text,                                     -- provider_id Unipile de la cible
  chat_id      text,                                     -- conversation créée (messages)
  error        text,
  created_at   timestamptz not null default now()
);

-- Lecture des compteurs : par user + type, filtrée sur une fenêtre temporelle.
create index if not exists idx_linkedin_outreach_actions_user
  on public.linkedin_outreach_actions(user_id, action_type, created_at desc);

alter table public.linkedin_outreach_actions enable row level security;

grant select, insert, update, delete on public.linkedin_outreach_actions to authenticated;

drop policy if exists "users_own_linkedin_outreach_actions" on public.linkedin_outreach_actions;
create policy "users_own_linkedin_outreach_actions"
  on public.linkedin_outreach_actions
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- 3. État d'outreach par lead.
alter table public.leads
  add column if not exists outreach_status text not null default 'none',  -- none | invite_sent | connected | messaged
  add column if not exists provider_id text,                              -- provider_id Unipile (résolu à l'invitation)
  add column if not exists outreach_chat_id text,                         -- conversation Unipile du premier message
  add column if not exists outreach_updated_at timestamptz;

comment on table public.linkedin_outreach_accounts is
  'Prospection LinkedIn (ALE-230) — compte Unipile connecté par client + config quota.';
comment on table public.linkedin_outreach_actions is
  'Prospection LinkedIn (ALE-230) — journal des invitations/messages envoyés (base des compteurs de quota).';
