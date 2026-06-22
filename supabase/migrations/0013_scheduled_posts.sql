-- ALE-96 : Programmer un post LinkedIn (planification)
-- Table des posts planifiés (cron backend → Zernio au moment voulu)

CREATE TABLE IF NOT EXISTS public.scheduled_posts (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    post_text   text NOT NULL,
    scheduled_at timestamptz NOT NULL,
    status      text NOT NULL DEFAULT 'pending',  -- pending | published | failed | cancelled
    zernio_post_id text,
    error_message text,
    created_at  timestamptz DEFAULT now(),
    updated_at  timestamptz DEFAULT now()
);

ALTER TABLE public.scheduled_posts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own scheduled posts"
    ON public.scheduled_posts FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

COMMENT ON TABLE public.scheduled_posts IS
    'Posts LinkedIn planifiés par les utilisateurs — publiés par le cron src/scheduler.py via Zernio.';
