-- Engagement hunter: mots-cles suivis + posts detectes.
-- A executer dans le SQL editor du projet Supabase zcxaxwqkswuefzlzpgvi.
--
-- RLS stricte : auth.uid() = user_id sur toutes les tables.

create table if not exists public.monitored_keywords (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  keyword text not null,
  enabled boolean not null default true,
  last_checked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint monitored_keywords_keyword_not_blank check (length(btrim(keyword)) > 0)
);

create table if not exists public.monitored_posts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  monitored_keyword_id uuid references public.monitored_keywords(id) on delete set null,
  linkedin_post_id text,
  post_url text not null,
  author_name text,
  author_url text,
  content text,
  published_at timestamptz,
  reactions_count int not null default 0,
  comments_count int not null default 0,
  reposts_count int not null default 0,
  raw_data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_monitored_keywords_user_enabled
  on public.monitored_keywords(user_id, enabled, created_at desc);
create unique index if not exists monitored_keywords_user_keyword_unique
  on public.monitored_keywords(user_id, lower(keyword));

create index if not exists idx_monitored_posts_user_created
  on public.monitored_posts(user_id, created_at desc);
create index if not exists idx_monitored_posts_keyword_created
  on public.monitored_posts(monitored_keyword_id, created_at desc);
create unique index if not exists monitored_posts_user_url_unique
  on public.monitored_posts(user_id, post_url);

alter table public.monitored_keywords enable row level security;
alter table public.monitored_posts enable row level security;

grant select, insert, update, delete on public.monitored_keywords to authenticated;
grant select, insert, update, delete on public.monitored_posts to authenticated;

drop policy if exists "monitored_keywords_select_own" on public.monitored_keywords;
drop policy if exists "monitored_keywords_insert_own" on public.monitored_keywords;
drop policy if exists "monitored_keywords_update_own" on public.monitored_keywords;
drop policy if exists "monitored_keywords_delete_own" on public.monitored_keywords;

create policy "monitored_keywords_select_own"
  on public.monitored_keywords
  for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "monitored_keywords_insert_own"
  on public.monitored_keywords
  for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "monitored_keywords_update_own"
  on public.monitored_keywords
  for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "monitored_keywords_delete_own"
  on public.monitored_keywords
  for delete
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "monitored_posts_select_own" on public.monitored_posts;
drop policy if exists "monitored_posts_insert_own" on public.monitored_posts;
drop policy if exists "monitored_posts_update_own" on public.monitored_posts;
drop policy if exists "monitored_posts_delete_own" on public.monitored_posts;

create policy "monitored_posts_select_own"
  on public.monitored_posts
  for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "monitored_posts_insert_own"
  on public.monitored_posts
  for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "monitored_posts_update_own"
  on public.monitored_posts
  for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "monitored_posts_delete_own"
  on public.monitored_posts
  for delete
  to authenticated
  using ((select auth.uid()) = user_id);

alter table public.leads
  drop constraint if exists leads_monitored_keyword_id_fkey,
  add constraint leads_monitored_keyword_id_fkey
    foreign key (monitored_keyword_id)
    references public.monitored_keywords(id)
    on delete set null;

alter table public.leads
  drop constraint if exists leads_source_post_id_fkey,
  add constraint leads_source_post_id_fkey
    foreign key (source_post_id)
    references public.monitored_posts(id)
    on delete set null;
