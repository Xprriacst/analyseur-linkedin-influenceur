-- 0048 — Prospection : moteur d'envoi cadencé (ALE-174, epic ALE-226)
--
-- Avant : un clic = un envoi immédiat. Les plafonds d'ALE-230 bornaient le VOLUME
-- (25/jour, ~100 invitations/7 j glissants) mais rien ne bornait le RYTHME : 25
-- invitations pouvaient partir en deux minutes, à 3 h du matin, le jour même de la
-- connexion du compte. C'est le profil de comportement que LinkedIn repère.
--
-- Après : l'action est MISE EN FILE (`linkedin_outreach_queue`) et un moteur de fond
-- (cron, `src/outreach_sender.py`) la sort au bon moment — plage horaire, jours
-- ouvrés, délai aléatoire entre deux actions, palier de warm-up, gel automatique.
--
-- (1) `linkedin_outreach_queue` : la file d'envoi (une ligne = une action à envoyer).
-- (2) colonnes de cadençage / warm-up / gel / dernier passage sur
--     `linkedin_outreach_accounts`.
-- (3) colonne `origin` sur le journal d'actions : distingue un envoi sorti de la file
--     d'un envoi immédiat (soupape « envoyer maintenant », plafonnée par jour).
--
-- ⚠️ Aucun compteur de quota n'est persisté ici : les compteurs restent CALCULÉS
-- depuis `linkedin_outreach_actions` sur fenêtres glissantes (auto-correctif, aucun
-- reset par cron à maintenir). Voir `db.outreach_counts`.
--
-- Idempotente (IF NOT EXISTS). RLS auth.uid() = user_id.

-- 1. File d'envoi.
create table if not exists public.linkedin_outreach_queue (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  lead_id      uuid not null references public.leads(id) on delete cascade,
  action_type  text not null,                          -- invite | message
  body         text,                                   -- texte du message (null pour une invitation)
  status       text not null default 'pending',        -- pending | sent | failed | canceled | skipped
  not_before   timestamptz not null default now(),     -- jamais avant cette date
  sent_at      timestamptz,
  error        text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- Le moteur cherche « la plus ancienne action due d'un utilisateur ».
create index if not exists idx_linkedin_outreach_queue_due
  on public.linkedin_outreach_queue(user_id, status, not_before);

-- Anti-double-clic : une seule action en attente par (lead, type). Un deuxième clic
-- sur « Inviter » ne peut pas empiler une deuxième invitation pour le même lead.
create unique index if not exists uniq_linkedin_outreach_queue_pending
  on public.linkedin_outreach_queue(lead_id, action_type)
  where status = 'pending';

alter table public.linkedin_outreach_queue enable row level security;

grant select, insert, update, delete on public.linkedin_outreach_queue to authenticated;

drop policy if exists "users_own_linkedin_outreach_queue" on public.linkedin_outreach_queue;
create policy "users_own_linkedin_outreach_queue"
  on public.linkedin_outreach_queue
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- 2. Cadençage, warm-up, gel et trace du dernier passage du moteur.
alter table public.linkedin_outreach_accounts
  -- Fenêtre d'envoi (heures de bureau du client, dans SON fuseau).
  add column if not exists timezone          text     not null default 'Europe/Paris',
  add column if not exists send_hour_start   smallint not null default 9,
  add column if not exists send_hour_end     smallint not null default 18,
  add column if not exists send_days         smallint[] not null default '{1,2,3,4,5}',  -- ISO : 1 = lundi … 7 = dimanche
  -- Warm-up : un compte neuf monte progressivement (voir outreach_engine.WARMUP_STEPS).
  -- Null → on retombe sur `connected_at` (aucun backfill nécessaire).
  add column if not exists warmup_started_at timestamptz,
  -- Gel automatique : posé par le moteur quand LinkedIn/Unipile signale une limite
  -- ou une restriction. NON contournable depuis l'interface — c'est ce qui protège
  -- le compte du client.
  add column if not exists frozen            boolean  not null default false,
  add column if not exists freeze_reason     text,
  add column if not exists frozen_at         timestamptz,
  -- Rythme : `next_action_at` = tirage aléatoire posé après chaque envoi.
  add column if not exists last_action_at    timestamptz,
  add column if not exists next_action_at    timestamptz,
  -- Observabilité : un cron qui plante en silence est pire qu'un cron absent.
  -- L'app affiche ces trois colonnes (« dernier passage il y a 8 min ») et lève un
  -- bandeau « ta prospection est à l'arrêt » si le moteur ne passe plus.
  add column if not exists last_run_at       timestamptz,
  add column if not exists last_run_sent     smallint not null default 0,
  add column if not exists last_run_error    text;

-- 2 bis. Le gel doit être INCONTOURNABLE, y compris hors de notre API.
--
-- La RLS autorise chaque client à modifier SA ligne de compte — avec sa clé anon et
-- son jeton, il pourrait donc écrire `frozen = false` en base directement depuis son
-- navigateur, sans passer par l'app, et se dégeler lui-même au pire moment. Un
-- garde-fou anti-restriction contournable n'en est pas un.
--
-- On restreint donc les colonnes que `authenticated` a le droit de METTRE À JOUR :
-- ses réglages, oui ; l'état de sécurité (gel, warm-up, compteurs de rythme, trace
-- du moteur), non — ceux-là n'appartiennent qu'au moteur, qui écrit en service-role
-- (lequel ignore et la RLS et les droits de colonne).
-- ⚠️ `user_id` doit rester modifiable : l'upsert de l'app (« on conflict user_id »)
-- écrit la colonne, et Postgres exige le droit UPDATE sur CHAQUE colonne du payload —
-- l'omettre casserait la connexion du compte et le réglage des quotas. Ce n'est pas un
-- trou : la RLS (`with check auth.uid() = user_id`) empêche d'y mettre l'id d'un autre.
revoke update on public.linkedin_outreach_accounts from authenticated;
grant update (
  user_id,
  unipile_account_id,
  account_name,
  status,
  daily_cap,
  weekly_invite_cap,
  timezone,
  send_hour_start,
  send_hour_end,
  send_days,
  updated_at
) on public.linkedin_outreach_accounts to authenticated;

-- 3. Origine d'un envoi : sorti de la file, ou envoi immédiat (soupape).
-- Les lignes existantes (ALE-230, envoi au clic) sont marquées 'manual'.
alter table public.linkedin_outreach_actions
  add column if not exists origin text not null default 'manual';  -- manual | queue | immediate

-- 3 bis. Le journal d'actions EST la source des compteurs de quota (fenêtres
-- glissantes). Or 0043 laissait `authenticated` le SUPPRIMER : un client pouvait
-- donc effacer son journal depuis son navigateur et remettre ses compteurs à zéro —
-- soit des plafonds « durs » contournables en une requête. On retire update/delete ;
-- select et insert suffisent à l'app (insérer une ligne ne peut que RESSERRER un
-- compteur, jamais le desserrer). Le moteur, en service-role, n'est pas concerné.
revoke update, delete on public.linkedin_outreach_actions from authenticated;

comment on table public.linkedin_outreach_queue is
  'Prospection LinkedIn (ALE-174) — file d''envoi : une action attend son créneau, le moteur cadencé la sort (plage horaire, délai aléatoire, warm-up, gel).';
comment on column public.linkedin_outreach_accounts.frozen is
  'Gel automatique posé par le moteur sur limite/restriction LinkedIn. Non contournable depuis l''interface.';
comment on column public.linkedin_outreach_accounts.last_run_at is
  'Dernier passage du moteur d''envoi. Affiché dans l''app ; son absence lève le bandeau « prospection à l''arrêt ».';
