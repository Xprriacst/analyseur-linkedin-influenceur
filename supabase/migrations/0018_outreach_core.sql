-- ALE-83 Phase 1 — Outreach: companies + leads
CREATE TABLE IF NOT EXISTS public.companies (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name        text NOT NULL,
  domain      text,
  industry    text,
  headcount_range text,
  hq_location text,
  linkedin_company_url text,
  status      text NOT NULL DEFAULT 'prospect' CHECK (status IN ('prospect', 'contacted', 'qualified', 'disqualified')),
  notes       text,
  metadata    jsonb DEFAULT '{}',
  created_at  timestamptz DEFAULT now(),
  updated_at  timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.leads (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  company_id  uuid REFERENCES public.companies(id) ON DELETE SET NULL,
  full_name   text NOT NULL,
  job_title   text,
  linkedin_profile_url text,
  email       text,
  status      text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'contacted', 'replied', 'meeting', 'qualified', 'disqualified')),
  notes       text,
  metadata    jsonb DEFAULT '{}',
  engaged_post_urls jsonb DEFAULT '[]',
  created_at  timestamptz DEFAULT now(),
  updated_at  timestamptz DEFAULT now()
);

ALTER TABLE public.leads REPLICA IDENTITY FULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_publication_tables
    WHERE pubname = 'supabase_realtime' AND tablename = 'leads'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.leads;
  END IF;
END$$;

ALTER TABLE public.companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.leads ENABLE ROW LEVEL SECURITY;

CREATE POLICY "companies_select" ON public.companies FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "companies_insert" ON public.companies FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "companies_update" ON public.companies FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "companies_delete" ON public.companies FOR DELETE USING (auth.uid() = user_id);

CREATE POLICY "leads_select" ON public.leads FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "leads_insert" ON public.leads FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "leads_update" ON public.leads FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "leads_delete" ON public.leads FOR DELETE USING (auth.uid() = user_id);
