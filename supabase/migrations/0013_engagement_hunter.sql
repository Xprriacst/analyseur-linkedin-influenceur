-- Engagement hunter : mots-clés surveillés + posts LinkedIn correspondants.
-- Les FK vers leads (monitored_keyword_id, source_post_id) sont ajoutées ici
-- après que les deux tables existent.
-- À exécuter manuellement dans le SQL editor Supabase.

create table if not exists public.monitored_keywords (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null default auth.uid() references auth.users(id) on delete cascade,
  keyword         text not null check (trim(keyword) <> ''),
  enabled         bool not null default true,
  last_checked_at timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (user_id, (lower(keyword)))
);

create table if not exists public.monitored_posts (
  id                   uuid primary key default gen_random_uuid(),
  user_id              uuid not null default auth.uid() references auth.users(id) on delete cascade,
  monitored_keyword_id uuid references public.monitored_keywords(id) on delete set null,
  linkedin_post_id     text,
  post_url             text not null,
  author_name          text,
  author_url           text,
  content              text,
  published_at         timestamptz,
  reactions_count      int default 0,
  comments_count       int default 0,
  reposts_count        int default 0,
  raw_data             jsonb not null default '{}',
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  unique (user_id, post_url)
);

alter table public.monitored_keywords enable row level security;
alter table public.monitored_posts enable row level security;

grant select, insert, update, delete on public.monitored_keywords to authenticated;
grant select, insert, update, delete on public.monitored_posts to authenticated;

drop policy if exists "monitored_keywords_select_own" on public.monitored_keywords;
drop policy if exists "monitored_keywords_insert_own" on public.monitored_keywords;
drop policy if exists "monitored_keywords_update_own" on public.monitored_keywords;
drop policy if exists "monitored_keywords_delete_own" on public.monitored_keywords;

create policy "monitored_keywords_select_own"
  on public.monitored_keywords for select to authenticated
  using ((select auth.uid()) = user_id);

create policy "monitored_keywords_insert_own"
  on public.monitored_keywords for insert to authenticated
  with check ((select auth.uid()) = user_id);

create policy "monitored_keywords_update_own"
  on public.monitored_keywords for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "monitored_keywords_delete_own"
  on public.monitored_keywords for delete to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "monitored_posts_select_own" on public.monitored_posts;
drop policy if exists "monitored_posts_insert_own" on public.monitored_posts;
drop policy if exists "monitored_posts_update_own" on public.monitored_posts;
drop policy if exists "monitored_posts_delete_own" on public.monitored_posts;

create policy "monitored_posts_select_own"
  on public.monitored_posts for select to authenticated
  using ((select auth.uid()) = user_id);

create policy "monitored_posts_insert_own"
  on public.monitored_posts for insert to authenticated
  with check ((select auth.uid()) = user_id);

create policy "monitored_posts_update_own"
  on public.monitored_posts for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "monitored_posts_delete_own"
  on public.monitored_posts for delete to authenticated
  using ((select auth.uid()) = user_id);

-- FK back-references from leads (created in 0012) to these tables.
alter table public.leads
  add constraint if not exists leads_monitored_keyword_id_fkey
  foreign key (monitored_keyword_id)
  references public.monitored_keywords(id) on delete set null;

alter table public.leads
  add constraint if not exists leads_source_post_id_fkey
  foreign key (source_post_id)
  references public.monitored_posts(id) on delete set null;
