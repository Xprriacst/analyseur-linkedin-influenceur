-- ALE-205 · Garde-fou + autopilot conditionnel de l'agent Instagram
-- Journal des décisions (tuning du seuil) + kill-switch global par utilisateur.
-- Idempotente.

-- Journal des décisions du garde-fou (auto-envoyé / escaladé / supervisé + raison).
CREATE TABLE IF NOT EXISTS public.ig_decisions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    conversation_id uuid REFERENCES public.ig_conversations(id) ON DELETE CASCADE,
    message_id      uuid,
    draft_id        uuid,
    decision        text NOT NULL,               -- auto_sent | escalated | supervised
    confidence      double precision,
    needs_human     boolean,
    reason          text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ig_decisions_conversation_idx
    ON public.ig_decisions (conversation_id, created_at);

ALTER TABLE public.ig_decisions ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "Users read own ig_decisions"
        ON public.ig_decisions FOR ALL
        USING (auth.uid() = user_id)
        WITH CHECK (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Kill-switch global par utilisateur : true → tout repasse en supervisé,
-- l'autopilot n'envoie plus rien quel que soit le mode des conversations.
ALTER TABLE public.user_editorial_profiles
    ADD COLUMN IF NOT EXISTS ig_autopilot_kill_switch boolean NOT NULL DEFAULT false;

COMMENT ON TABLE public.ig_decisions IS
    'Agent qualification Instagram — journal des décisions garde-fou/autopilot (ALE-205).';
COMMENT ON COLUMN public.user_editorial_profiles.ig_autopilot_kill_switch IS
    'Kill-switch global : true = tout en supervisé, aucun envoi autopilot (ALE-205).';
