-- Profil editorial utilisateur, utilise comme contexte client dans les prompts IA.
-- Une ligne par utilisateur pour cette premiere version (multi-clients possible plus tard).

create table if not exists public.user_editorial_profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  display_name text,
  brand_name text,
  industry text,
  business_description text,
  location text,
  target_audience text,
  core_offer text,
  tone text,
  linkedin_objective text,
  topics_to_cover text,
  topics_to_avoid text,
  constraints text,
  website_url text,
  linkedin_url text,
  language text default 'francais',
  market text,
  extra_context text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint user_editorial_profiles_user_unique unique (user_id)
);

create index if not exists idx_user_editorial_profiles_user
  on public.user_editorial_profiles(user_id);

alter table public.user_editorial_profiles enable row level security;

grant select, insert, update, delete
  on public.user_editorial_profiles
  to authenticated;

drop policy if exists "editorial_profiles_select_own" on public.user_editorial_profiles;
drop policy if exists "editorial_profiles_insert_own" on public.user_editorial_profiles;
drop policy if exists "editorial_profiles_update_own" on public.user_editorial_profiles;
drop policy if exists "editorial_profiles_delete_own" on public.user_editorial_profiles;

create policy "editorial_profiles_select_own"
  on public.user_editorial_profiles
  for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "editorial_profiles_insert_own"
  on public.user_editorial_profiles
  for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "editorial_profiles_update_own"
  on public.user_editorial_profiles
  for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "editorial_profiles_delete_own"
  on public.user_editorial_profiles
  for delete
  to authenticated
  using ((select auth.uid()) = user_id);
