-- Migration 001: Core tables (companies, sales_searches, leads)
-- Run this in the Supabase SQL Editor
-- RLS is disabled for now — will be added when we introduce Auth

-- ============================================================
-- 1. companies
-- ============================================================
create table public.companies (
  id bigint generated always as identity primary key,
  linkedin_id text not null,
  name text,
  website text,
  industry text,
  headcount text,
  created_at timestamptz default now(),

  constraint companies_linkedin_id_unique unique (linkedin_id)
);

create index idx_companies_linkedin_id on public.companies (linkedin_id);

-- ============================================================
-- 2. sales_searches  (replaces NocoDB table "Sales" maawydukohaxbsy)
-- ============================================================
create table public.sales_searches (
  id bigint generated always as identity primary key,
  extract_status text not null default 'nouvelle extraction'
    check (extract_status in ('nouvelle extraction', 'en cours', 'complété', 'en pause')),
  salesnav_extraction jsonb,
  edit_extract text,
  extracted_leads_this_search int default 0,
  linkedin_account text,
  cursor text,
  list_id text,
  profile_views_today int default 0,
  location text,
  current_search_page int default 0,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- ============================================================
-- 3. leads  (replaces NocoDB table "Leads" mfphgxk60o36su1)
--    Fields cover both n8n (scraping) and polaris (UI) needs.
-- ============================================================
create table public.leads (
  id bigint generated always as identity primary key,

  -- n8n fields (populated by scraping workflow)
  name text,
  linkedin_profile_url text,
  headline text,
  invitation_connection text default 'non envoyée'
    check (invitation_connection in ('acceptée', 'envoyée', 'non envoyée')),
  member_urn text,
  classic_id text,
  salesnav_id text,
  extracted_date date,
  latest_refresh timestamptz,

  -- polaris fields (populated by UI / seed)
  first_name text,
  last_name text,
  role text,
  company_name text,
  avatar_color text,
  signal text,
  signal_text text,
  score int default 1 check (score between 1 and 3),
  status text default 'to-validate'
    check (status in ('to-validate', 'in-progress', 'replied')),
  location text,
  industry text,
  company_size text,
  proposed_message text,
  post_preview text,

  -- foreign keys
  company_id bigint references public.companies(id),
  sales_search_id bigint references public.sales_searches(id),

  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index idx_leads_company_id on public.leads (company_id);
create index idx_leads_sales_search_id on public.leads (sales_search_id);
create index idx_leads_status on public.leads (status);
create index idx_leads_salesnav_id on public.leads (salesnav_id);

-- ============================================================
-- Disable RLS for now (we'll enable it when Auth is added)
-- ============================================================
alter table public.companies enable row level security;
create policy "Allow all on companies" on public.companies for all using (true) with check (true);

alter table public.sales_searches enable row level security;
create policy "Allow all on sales_searches" on public.sales_searches for all using (true) with check (true);

alter table public.leads enable row level security;
create policy "Allow all on leads" on public.leads for all using (true) with check (true);
