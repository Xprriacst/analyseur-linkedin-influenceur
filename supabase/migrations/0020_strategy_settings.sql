-- ALE-83 Phase 1 — Strategy settings (1 row per user)
CREATE TABLE IF NOT EXISTS public.strategy_settings (
  id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                 uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  tone                    text DEFAULT 'professional',
  target_audience         text,
  value_proposition       text,
  message_template_1      text,
  message_template_2      text,
  auto_outreach_enabled   boolean NOT NULL DEFAULT false,
  created_at              timestamptz DEFAULT now(),
  updated_at              timestamptz DEFAULT now(),
  UNIQUE(user_id)
);

ALTER TABLE public.strategy_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "strategy_select" ON public.strategy_settings FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "strategy_insert" ON public.strategy_settings FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "strategy_update" ON public.strategy_settings FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "strategy_delete" ON public.strategy_settings FOR DELETE USING (auth.uid() = user_id);
