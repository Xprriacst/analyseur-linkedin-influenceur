-- Boucle d'apprentissage des réponses IA suggérées (ALE-253).
--
-- Capture chaque suggestion IA (Instagram ou LinkedIn) au moment de l'envoi,
-- éditée ou non, pour nourrir une base de règles apprises par canal, distillée
-- périodiquement (cron) et réinjectée dans les prompts de génération — sur le
-- même principe que la FAQ éditable de l'agent Instagram (ig_faqs).
--
-- Idempotente (IF NOT EXISTS). RLS auth.uid() = user_id.

CREATE TABLE IF NOT EXISTS public.ai_reply_feedback (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    channel           text NOT NULL CHECK (channel IN ('instagram', 'linkedin')),
    conversation_ref  text,
    suggested_text    text NOT NULL,
    sent_text         text NOT NULL,
    edited            boolean NOT NULL,
    learn_opt_out     boolean NOT NULL DEFAULT false,
    learned_at        timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ai_reply_feedback_pending_idx
    ON public.ai_reply_feedback (user_id, channel)
    WHERE learned_at IS NULL AND learn_opt_out = false AND edited = true;

ALTER TABLE public.ai_reply_feedback ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "Users read own ai_reply_feedback"
        ON public.ai_reply_feedback FOR SELECT
        USING (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE POLICY "Users insert own ai_reply_feedback"
        ON public.ai_reply_feedback FOR INSERT
        WITH CHECK (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Journal d'apprentissage : append-only côté client, comme
-- linkedin_outreach_actions (0043). `learned_at` n'est posé que par le cron
-- (service-role, hors RLS) — un client ne doit pas pouvoir se retirer après
-- coup de la file de distillation en modifiant/supprimant ses propres lignes.
REVOKE UPDATE, DELETE ON public.ai_reply_feedback FROM authenticated;

COMMENT ON TABLE public.ai_reply_feedback IS
    'Suggestion IA vs texte réellement envoyé, par message (Instagram + LinkedIn) — signal brut pour la distillation de règles apprises (ALE-253).';

CREATE TABLE IF NOT EXISTS public.ai_learned_rules (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    channel            text NOT NULL CHECK (channel IN ('instagram', 'linkedin')),
    content            text NOT NULL DEFAULT '',
    last_distilled_at  timestamptz,
    updated_at         timestamptz NOT NULL DEFAULT now(),
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, channel)
);

ALTER TABLE public.ai_learned_rules ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "Users manage own ai_learned_rules"
        ON public.ai_learned_rules FOR ALL
        USING (auth.uid() = user_id)
        WITH CHECK (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TABLE public.ai_learned_rules IS
    'Règles apprises par canal, distillées depuis ai_reply_feedback et injectées dans les prompts de génération — visibles/éditables par le client (ALE-253).';
