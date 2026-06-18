-- Strategie outreach par utilisateur.
-- Remplace le localStorage de Polaris par une table Supabase scopee user_id.

create table if not exists public.strategy_settings (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  target_titles text[] not null default '{}'::text[],
  target_industries text[] not null default '{}'::text[],
  target_company_sizes text[] not null default '{}'::text[],
  target_locations text[] not null default '{}'::text[],
  signals text[] not null default '{}'::text[],
  tone text,
  never_do text[] not null default '{}'::text[],
  weekly_volume int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint strategy_settings_user_unique unique (user_id),
  constraint strategy_settings_weekly_volume_positive check (weekly_volume >= 0)
);

create index if not exists idx_strategy_settings_user
  on public.strategy_settings(user_id);

alter table public.strategy_settings enable row level security;

grant select, insert, update, delete on public.strategy_settings to authenticated;

drop policy if exists "strategy_settings_select_own" on public.strategy_settings;
drop policy if exists "strategy_settings_insert_own" on public.strategy_settings;
drop policy if exists "strategy_settings_update_own" on public.strategy_settings;
drop policy if exists "strategy_settings_delete_own" on public.strategy_settings;

create policy "strategy_settings_select_own"
  on public.strategy_settings
  for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "strategy_settings_insert_own"
  on public.strategy_settings
  for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "strategy_settings_update_own"
  on public.strategy_settings
  for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "strategy_settings_delete_own"
  on public.strategy_settings
  for delete
  to authenticated
  using ((select auth.uid()) = user_id);
