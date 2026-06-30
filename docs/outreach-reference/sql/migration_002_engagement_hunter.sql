-- Migration 002: Engagement Hunter (pivot vers approche Gojiberry)
-- Run this in the Supabase SQL Editor AFTER migration_001.
-- Adds the engagement-based monitoring layer (no Sales Navigator required).

-- ============================================================
-- 1. monitored_keywords
--    Mots-clés surveillés en continu pour trouver des posts LinkedIn pertinents.
--    Chaque keyword génère des leads via les engagers (likers + commenters) des posts.
-- ============================================================
create table public.monitored_keywords (
  id bigint generated always as identity primary key,

  -- Configuration de tracking
  keyword text not null,
  description text, -- ex: "Posts mentionnant 'conciergerie' pour cibler les agences"
  is_active boolean not null default true,

  -- Filtres de search Unipile (api: classic, category: posts)
  date_posted text not null default 'past_week'
    check (date_posted in ('past_24h', 'past_week', 'past_month')),
  content_type text -- 'images' | 'videos' | null (any)
    check (content_type is null or content_type in ('images', 'videos', 'documents', 'live_videos')),
  author_keywords text, -- ex: "CEO" pour filtrer les posts par job title de l'auteur
  sort_by text not null default 'date'
    check (sort_by in ('date', 'relevance')),

  -- Compte LinkedIn Unipile à utiliser pour la search
  linkedin_account text,

  -- Stats / état
  posts_found_total int not null default 0,
  leads_found_total int not null default 0,
  last_run_at timestamptz,
  last_error text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index idx_monitored_keywords_active on public.monitored_keywords (is_active);
create index idx_monitored_keywords_keyword on public.monitored_keywords (keyword);

-- ============================================================
-- 2. monitored_posts
--    Cache des posts trouvés par la search Unipile.
--    Évite de retraiter le même post plusieurs fois.
-- ============================================================
create table public.monitored_posts (
  id bigint generated always as identity primary key,

  social_id text not null, -- urn:li:activity:XXXX (clé stable Unipile)
  share_url text,
  text_content text,

  -- Auteur
  author_public_id text,
  author_name text,
  author_headline text,
  author_is_company boolean default false,

  -- Stats
  reaction_counter int default 0,
  comment_counter int default 0,
  parsed_datetime timestamptz,

  -- Lien vers le keyword qui a déclenché la découverte
  monitored_keyword_id bigint references public.monitored_keywords(id) on delete cascade,

  -- Statut de processing des engagers
  engagers_fetched_at timestamptz,
  engagers_count int default 0,

  created_at timestamptz not null default now(),

  constraint monitored_posts_social_id_unique unique (social_id)
);

create index idx_monitored_posts_keyword on public.monitored_posts (monitored_keyword_id);
create index idx_monitored_posts_social_id on public.monitored_posts (social_id);

-- ============================================================
-- 3. Adaptation table `leads` pour tracer la provenance engagement
-- ============================================================
alter table public.leads
  add column if not exists monitored_keyword_id bigint references public.monitored_keywords(id),
  add column if not exists source_post_id bigint references public.monitored_posts(id),
  add column if not exists engagement_type text
    check (engagement_type is null or engagement_type in ('reaction', 'comment'));

create index if not exists idx_leads_monitored_keyword_id
  on public.leads (monitored_keyword_id);

-- ============================================================
-- 4. RLS (permissif pour l'instant, à durcir avec Auth)
-- ============================================================
alter table public.monitored_keywords enable row level security;
create policy "Allow all on monitored_keywords"
  on public.monitored_keywords for all using (true) with check (true);

alter table public.monitored_posts enable row level security;
create policy "Allow all on monitored_posts"
  on public.monitored_posts for all using (true) with check (true);

-- ============================================================
-- 5. Realtime publication (pour que l'UI se mette à jour live)
-- ============================================================
alter publication supabase_realtime add table public.monitored_keywords;
alter publication supabase_realtime add table public.monitored_posts;
