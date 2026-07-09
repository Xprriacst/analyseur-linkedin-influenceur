-- 0041 — Prospection LinkedIn, brique 1 (ALE-227, epic ALE-226)
-- (1) `lead_sources` : posts concurrents importés (manuellement ou via la veille),
--     avec le verdict lead-magnet + mot-clé déclencheur (« commente CLOUD… » → CLOUD).
-- (2) `leads` : commentateurs récupérés, UNE ligne par personne et par utilisateur —
--     une personne qui commente chez plusieurs concurrents accumule des signaux
--     (jsonb `signals`, un par source) au lieu d'être dupliquée.

create table if not exists public.lead_sources (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  post_url text not null,
  author text,
  post_text text,
  is_lead_magnet boolean not null default false,
  trigger_keyword text,
  origin text not null default 'manual',        -- 'manual' | 'monitoring'
  comments_count integer,                        -- nb de commentaires récupérés (journalisation coût)
  collected_at timestamptz,                      -- null = commentateurs jamais collectés
  created_at timestamptz not null default now(),
  constraint lead_sources_user_post_unique unique (user_id, post_url)
);

create index if not exists idx_lead_sources_user
  on public.lead_sources(user_id, created_at desc);

alter table public.lead_sources enable row level security;

grant select, insert, update, delete on public.lead_sources to authenticated;

drop policy if exists "users_own_lead_sources" on public.lead_sources;
create policy "users_own_lead_sources"
  on public.lead_sources
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create table if not exists public.leads (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  profile_url text not null,
  name text,
  headline text,
  -- Dernier signal en date (affichage liste) ; l'historique complet est dans `signals`.
  source_id uuid references public.lead_sources(id) on delete set null,
  comment_text text,
  commented_at timestamptz,
  reaction_count integer not null default 0,
  -- Un signal = un commentaire sous une source : {source_id, post_url, author,
  -- trigger_keyword, comment_text, commented_at}. Dédup par (personne, source).
  signals jsonb not null default '[]'::jsonb,
  signal_count integer not null default 1,       -- > 1 = « multi-signaux »
  status text not null default 'new',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint leads_user_profile_unique unique (user_id, profile_url)
);

create index if not exists idx_leads_user
  on public.leads(user_id, created_at desc);
create index if not exists idx_leads_source
  on public.leads(source_id);

alter table public.leads enable row level security;

grant select, insert, update, delete on public.leads to authenticated;

drop policy if exists "users_own_leads" on public.leads;
create policy "users_own_leads"
  on public.leads
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
