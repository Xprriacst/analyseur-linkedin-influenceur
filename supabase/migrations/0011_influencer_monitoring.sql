-- ALE-32: Monitoring influenceurs — suivi automatique des nouveaux posts.
-- À exécuter manuellement dans le SQL editor Supabase avant de déployer le cron.

CREATE TABLE IF NOT EXISTS public.influencer_monitoring (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    influencer_id uuid NOT NULL REFERENCES public.influencers(id) ON DELETE CASCADE,
    -- 'daily' (vérification ~quotidienne) | 'weekly'
    frequency text NOT NULL DEFAULT 'daily' CHECK (frequency IN ('daily', 'weekly')),
    is_active boolean NOT NULL DEFAULT true,
    last_monitored_at timestamptz,
    -- Nombre de nouveaux posts détectés lors de la dernière vérification
    new_posts_since_last int NOT NULL DEFAULT 0,
    created_at timestamptz DEFAULT now()
);

-- 1 entrée par paire (user, influenceur)
CREATE UNIQUE INDEX IF NOT EXISTS idx_monitoring_user_influencer
    ON public.influencer_monitoring(user_id, influencer_id);

-- Index pour le cron (ne lit que les actifs)
CREATE INDEX IF NOT EXISTS idx_monitoring_active
    ON public.influencer_monitoring(is_active, last_monitored_at)
    WHERE is_active = true;

ALTER TABLE public.influencer_monitoring ENABLE ROW LEVEL SECURITY;

CREATE POLICY "monitoring_user_rls"
    ON public.influencer_monitoring
    FOR ALL USING (auth.uid() = user_id);
