-- Migration 0026 : Outreach — schéma de détection (Engagement Hunter)
-- Issue ALE-169 — Outreach 1/6
-- Toutes les tables : user_id uuid scopé, RLS auth.uid() = user_id, idempotentes (IF NOT EXISTS).

-- ============================================================
-- 1. monitored_keywords — mots-clés LinkedIn à surveiller
-- ============================================================
create table if not exists public.monitored_keywords (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,

  keyword text not null,
  description text,
  is_active boolean not null default true,

  -- Paramètres de recherche Apify
  date_posted text not null default 'past_week'
    check (date_posted in ('past_24h', 'past_week', 'past_month')),
  content_type text
    check (content_type is null or content_type in ('images', 'videos', 'documents', 'live_videos')),
  author_keywords text,
  sort_by text not null default 'date'
    check (sort_by in ('date', 'relevance')),

  -- Stats / état
  posts_found_total int not null default 0,
  leads_found_total int not null default 0,
  last_run_at timestamptz,
  last_error text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_monitored_keywords_user
  on public.monitored_keywords (user_id);
create index if not exists idx_monitored_keywords_active
  on public.monitored_keywords (user_id, is_active);

alter table public.monitored_keywords enable row level security;

do $$ begin
  if not exists (
    select 1 from pg_policies
    where tablename = 'monitored_keywords' and policyname = 'User owns monitored_keywords'
  ) then
    create policy "User owns monitored_keywords"
      on public.monitored_keywords for all
      using ((select auth.uid()) = user_id)
      with check ((select auth.uid()) = user_id);
  end if;
end $$;

-- ============================================================
-- 2. monitored_posts — cache des posts trouvés par Apify
-- ============================================================
create table if not exists public.monitored_posts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,

  social_id text not null,   -- urn:li:activity:XXXX (clé stable Apify)
  share_url text,
  text_content text,

  -- Auteur
  author_public_id text,
  author_name text,
  author_headline text,
  author_is_company boolean default false,

  -- Engagement
  reaction_counter int default 0,
  comment_counter int default 0,
  parsed_datetime timestamptz,

  monitored_keyword_id uuid references public.monitored_keywords(id) on delete set null,

  -- Statut de traitement des engagers
  engagers_fetched_at timestamptz,
  engagers_count int default 0,

  created_at timestamptz not null default now(),

  -- Dédup par utilisateur (le même post peut être suivi par plusieurs users)
  constraint monitored_posts_user_social_id_unique unique (user_id, social_id)
);

create index if not exists idx_monitored_posts_user
  on public.monitored_posts (user_id);
create index if not exists idx_monitored_posts_keyword
  on public.monitored_posts (monitored_keyword_id);

alter table public.monitored_posts enable row level security;

do $$ begin
  if not exists (
    select 1 from pg_policies
    where tablename = 'monitored_posts' and policyname = 'User owns monitored_posts'
  ) then
    create policy "User owns monitored_posts"
      on public.monitored_posts for all
      using ((select auth.uid()) = user_id)
      with check ((select auth.uid()) = user_id);
  end if;
end $$;

-- ============================================================
-- 3. outreach_leads — leads détectés via l'Engagement Hunter
-- ============================================================
create table if not exists public.outreach_leads (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,

  name text,
  first_name text,
  last_name text,
  headline text,
  role text,
  company_name text,
  linkedin_profile_url text not null,

  signal text,         -- ex. "engaged-content"
  signal_text text,    -- ex. "A liké un post sur «IA RH»"
  score int default 2 check (score between 1 and 3),
  status text not null default 'to-validate'
    check (status in ('to-validate', 'in-progress', 'replied', 'skipped')),
  engagement_type text
    check (engagement_type is null or engagement_type in ('reaction', 'comment')),

  monitored_keyword_id uuid references public.monitored_keywords(id) on delete set null,
  source_post_id uuid references public.monitored_posts(id) on delete set null,

  proposed_message text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  -- Un même profil LinkedIn une seule fois par utilisateur
  constraint outreach_leads_user_url_unique unique (user_id, linkedin_profile_url)
);

create index if not exists idx_outreach_leads_user
  on public.outreach_leads (user_id);
create index if not exists idx_outreach_leads_status
  on public.outreach_leads (user_id, status);
create index if not exists idx_outreach_leads_keyword
  on public.outreach_leads (monitored_keyword_id);

alter table public.outreach_leads enable row level security;

do $$ begin
  if not exists (
    select 1 from pg_policies
    where tablename = 'outreach_leads' and policyname = 'User owns outreach_leads'
  ) then
    create policy "User owns outreach_leads"
      on public.outreach_leads for all
      using ((select auth.uid()) = user_id)
      with check ((select auth.uid()) = user_id);
  end if;
end $$;
