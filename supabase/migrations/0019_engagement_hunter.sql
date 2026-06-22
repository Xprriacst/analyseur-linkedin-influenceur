-- ALE-83 Phase 1 — Engagement Hunter: monitored_keywords + monitored_posts
CREATE TABLE IF NOT EXISTS public.monitored_keywords (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  keyword     text NOT NULL,
  description text,
  status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
  match_count int NOT NULL DEFAULT 0,
  last_run_at timestamptz,
  created_at  timestamptz DEFAULT now(),
  UNIQUE(user_id, keyword)
);

CREATE TABLE IF NOT EXISTS public.monitored_posts (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  keyword_id          uuid NOT NULL REFERENCES public.monitored_keywords(id) ON DELETE CASCADE,
  author_linkedin_url text,
  author_name         text,
  post_url            text NOT NULL,
  post_content        text,
  posted_at           timestamptz,
  likes_count         int DEFAULT 0,
  comments_count      int DEFAULT 0,
  relevance_score     numeric(3,2),
  processed           boolean NOT NULL DEFAULT false,
  lead_id             uuid REFERENCES public.leads(id) ON DELETE SET NULL,
  created_at          timestamptz DEFAULT now(),
  UNIQUE(keyword_id, post_url)
);

ALTER TABLE public.monitored_keywords ENABLE ROW LEVEL SECURITY;

CREATE POLICY "keywords_select" ON public.monitored_keywords FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "keywords_insert" ON public.monitored_keywords FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "keywords_update" ON public.monitored_keywords FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "keywords_delete" ON public.monitored_keywords FOR DELETE USING (auth.uid() = user_id);

ALTER TABLE public.monitored_posts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "posts_select" ON public.monitored_posts FOR SELECT
  USING (keyword_id IN (SELECT id FROM public.monitored_keywords WHERE user_id = auth.uid()));
CREATE POLICY "posts_insert" ON public.monitored_posts FOR INSERT
  WITH CHECK (keyword_id IN (SELECT id FROM public.monitored_keywords WHERE user_id = auth.uid()));
CREATE POLICY "posts_update" ON public.monitored_posts FOR UPDATE
  USING (keyword_id IN (SELECT id FROM public.monitored_keywords WHERE user_id = auth.uid()));
CREATE POLICY "posts_delete" ON public.monitored_posts FOR DELETE
  USING (keyword_id IN (SELECT id FROM public.monitored_keywords WHERE user_id = auth.uid()));
