-- Outreach core: companies + leads.
-- A executer dans le SQL editor du projet Supabase zcxaxwqkswuefzlzpgvi.
--
-- RLS stricte : chaque utilisateur ne lit/ecrit que ses propres lignes.
-- Les FK vers monitored_keywords/monitored_posts sont ajoutees par 0006, une
-- fois ces tables creees.

create table if not exists public.companies (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name text not null,
  domain text,
  website_url text,
  linkedin_url text,
  industry text,
  company_size text,
  location text,
  description text,
  raw_data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.leads (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  company_id uuid references public.companies(id) on delete set null,
  monitored_keyword_id uuid,
  source_post_id uuid,
  first_name text,
  last_name text,
  full_name text not null,
  title text,
  linkedin_url text,
  email text,
  phone text,
  company_name text,
  source_url text,
  engagement_type text,
  score int not null default 0,
  status text not null default 'new',
  signal jsonb not null default '{}'::jsonb,
  raw_data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint leads_score_range check (score >= 0 and score <= 100),
  constraint leads_status_allowed check (
    status in ('new', 'qualified', 'contacted', 'replied', 'converted', 'archived')
  )
);

create index if not exists idx_companies_user_created
  on public.companies(user_id, created_at desc);
create index if not exists idx_companies_user_domain
  on public.companies(user_id, lower(domain))
  where domain is not null;

create index if not exists idx_leads_user_created
  on public.leads(user_id, created_at desc);
create index if not exists idx_leads_user_status
  on public.leads(user_id, status, created_at desc);
create index if not exists idx_leads_company
  on public.leads(company_id);
create index if not exists idx_leads_monitored_keyword
  on public.leads(monitored_keyword_id);
create index if not exists idx_leads_source_post
  on public.leads(source_post_id);

alter table public.companies enable row level security;
alter table public.leads enable row level security;

grant select, insert, update, delete on public.companies to authenticated;
grant select, insert, update, delete on public.leads to authenticated;

drop policy if exists "companies_select_own" on public.companies;
drop policy if exists "companies_insert_own" on public.companies;
drop policy if exists "companies_update_own" on public.companies;
drop policy if exists "companies_delete_own" on public.companies;

create policy "companies_select_own"
  on public.companies
  for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "companies_insert_own"
  on public.companies
  for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "companies_update_own"
  on public.companies
  for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "companies_delete_own"
  on public.companies
  for delete
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "leads_select_own" on public.leads;
drop policy if exists "leads_insert_own" on public.leads;
drop policy if exists "leads_update_own" on public.leads;
drop policy if exists "leads_delete_own" on public.leads;

create policy "leads_select_own"
  on public.leads
  for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "leads_insert_own"
  on public.leads
  for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "leads_update_own"
  on public.leads
  for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "leads_delete_own"
  on public.leads
  for delete
  to authenticated
  using ((select auth.uid()) = user_id);

alter table public.leads replica identity full;

do $$
begin
  if not exists (
    select 1
    from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'leads'
  ) then
    execute 'alter publication supabase_realtime add table public.leads';
  end if;
end $$;
