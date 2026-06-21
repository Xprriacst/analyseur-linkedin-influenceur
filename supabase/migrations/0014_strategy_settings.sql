-- Paramètres de stratégie outreach par utilisateur (1 ligne par user).
-- À exécuter manuellement dans le SQL editor Supabase.

create table if not exists public.strategy_settings (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid not null default auth.uid() references auth.users(id) on delete cascade,
  target_titles         text[] not null default '{}',
  target_industries     text[] not null default '{}',
  target_company_sizes  text[] not null default '{}',
  target_locations      text[] not null default '{}',
  signals               text[] not null default '{}',
  tone                  text,
  never_do              text[] not null default '{}',
  weekly_volume         int not null default 0,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (user_id)
);

alter table public.strategy_settings enable row level security;

grant select, insert, update, delete on public.strategy_settings to authenticated;

drop policy if exists "strategy_settings_select_own" on public.strategy_settings;
drop policy if exists "strategy_settings_insert_own" on public.strategy_settings;
drop policy if exists "strategy_settings_update_own" on public.strategy_settings;
drop policy if exists "strategy_settings_delete_own" on public.strategy_settings;

create policy "strategy_settings_select_own"
  on public.strategy_settings for select to authenticated
  using ((select auth.uid()) = user_id);

create policy "strategy_settings_insert_own"
  on public.strategy_settings for insert to authenticated
  with check ((select auth.uid()) = user_id);

create policy "strategy_settings_update_own"
  on public.strategy_settings for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "strategy_settings_delete_own"
  on public.strategy_settings for delete to authenticated
  using ((select auth.uid()) = user_id);
