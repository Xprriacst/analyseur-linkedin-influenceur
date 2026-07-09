-- 0042 — Prospection LinkedIn, brique 2 (ALE-228, epic ALE-226)
-- (1) `lead_targeting` : la config de ciblage ICP par utilisateur (client idéal,
--     offre, mots-clés d'intérêt, seuil de score, consignes du 1er message).
--     Pré-remplie depuis le profil éditorial mais éditable indépendamment (on ne
--     réécrit jamais dans user_editorial_profiles).
-- (2) colonnes de score sur `leads` : le LLM note chaque lead 0-100 vs le ciblage
--     + une justification d'une phrase. Les leads sous le seuil restent en base
--     mais sont masqués de la liste (filtrage côté lecture).

create table if not exists public.lead_targeting (
  user_id uuid primary key references auth.users(id) on delete cascade,
  ideal_client text,                              -- à qui je veux vendre
  offer text,                                     -- ce que je vends
  interest_keywords jsonb not null default '[]'::jsonb,  -- signaux d'intérêt (mots-clés)
  score_threshold integer not null default 60,    -- 0-100 : sous ce seuil, lead masqué
  first_message_instructions text,                -- consignes du 1er message (ton, longueur, CTA…) — sert à ALE-230
  updated_at timestamptz not null default now()
);

alter table public.lead_targeting enable row level security;

grant select, insert, update, delete on public.lead_targeting to authenticated;

drop policy if exists "users_own_lead_targeting" on public.lead_targeting;
create policy "users_own_lead_targeting"
  on public.lead_targeting
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

alter table public.leads
  add column if not exists score integer,          -- 0-100, null = pas encore noté (toujours affiché)
  add column if not exists score_reason text,      -- justification LLM d'une phrase
  add column if not exists scored_at timestamptz;
