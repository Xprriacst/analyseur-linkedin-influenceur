-- Lead finder (détection de signaux d'intention) : on colle l'URL d'un post
-- LinkedIn, on récupère les personnes qui l'ont commenté → leads exploitables.
-- Une recherche (`lead_searches`) = un scrape ; ses résultats (`leads`) lui sont
-- rattachés. Tout est scopé par utilisateur (RLS auth.uid() = user_id).

create table if not exists public.lead_searches (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  source text not null default 'post_comments',   -- type de signal ('post_comments')
  post_url text not null,                          -- URL du post LinkedIn analysé
  influencer_name text,                            -- nom de l'auteur du post (si dispo)
  max_items int not null default 50,               -- plafond demandé au scrape
  lead_count int not null default 0,               -- nb de leads trouvés
  created_at timestamptz default now()
);

create table if not exists public.leads (
  id uuid primary key default gen_random_uuid(),
  search_id uuid not null references public.lead_searches(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  name text,
  headline text,                                   -- poste / accroche du profil
  profile_url text,                                -- URL du profil LinkedIn
  comment_text text,                               -- le commentaire laissé
  commented_at timestamptz,
  reaction_count int not null default 0,           -- likes reçus par le commentaire
  created_at timestamptz default now(),
  -- Dédup : un même profil ne figure qu'une fois par recherche.
  constraint leads_search_profile_unique unique (search_id, profile_url)
);

create index if not exists idx_lead_searches_user
  on public.lead_searches(user_id, created_at desc);
create index if not exists idx_leads_search
  on public.leads(search_id, created_at desc);

alter table public.lead_searches enable row level security;
alter table public.leads enable row level security;

grant select, insert, update, delete on public.lead_searches to authenticated;
grant select, insert, update, delete on public.leads to authenticated;

drop policy if exists "users_own_lead_searches" on public.lead_searches;
create policy "users_own_lead_searches"
  on public.lead_searches
  for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists "users_own_leads" on public.leads;
create policy "users_own_leads"
  on public.leads
  for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
