-- ALE-201 · Agent de pré-qualification prospects Instagram (fondation)
-- Modèle de données du module IG : conversations, messages, réponses suggérées.
-- Idempotente (IF NOT EXISTS). RLS auth.uid() = user_id sur les 3 tables.

-- 1. Conversations (une par prospect IG / compte app).
CREATE TABLE IF NOT EXISTS public.ig_conversations (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    prospect_id       text NOT NULL,               -- subscriber id ManyChat (identifiant IG côté middleware)
    prospect_name     text,
    status            text NOT NULL DEFAULT 'open', -- open | qualified | closed
    mode              text NOT NULL DEFAULT 'supervised', -- supervised | autopilot
    last_message_at   timestamptz,
    last_inbound_at   timestamptz,                 -- dernier message DU prospect (base de la fenêtre 24 h Meta)
    window_expires_at timestamptz,                 -- last_inbound_at + 24 h : au-delà, plus d'envoi conforme
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, prospect_id)
);

ALTER TABLE public.ig_conversations ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "Users manage own ig_conversations"
        ON public.ig_conversations FOR ALL
        USING (auth.uid() = user_id)
        WITH CHECK (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 2. Messages (in = prospect, out = agent/humain).
CREATE TABLE IF NOT EXISTS public.ig_messages (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL REFERENCES public.ig_conversations(id) ON DELETE CASCADE,
    user_id         uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role            text NOT NULL,               -- in | out
    source          text NOT NULL,               -- prospect | agent | human
    text            text NOT NULL DEFAULT '',
    kind            text NOT NULL DEFAULT 'text', -- text | voice (voice = transcrit, cf. ALE-203)
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ig_messages_conversation_idx
    ON public.ig_messages (conversation_id, created_at);

ALTER TABLE public.ig_messages ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "Users manage own ig_messages"
        ON public.ig_messages FOR ALL
        USING (auth.uid() = user_id)
        WITH CHECK (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 3. Réponses suggérées par l'agent (draft généré en ALE-202, envoyé en 204/205).
CREATE TABLE IF NOT EXISTS public.ig_drafts (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id      uuid NOT NULL REFERENCES public.ig_messages(id) ON DELETE CASCADE,
    conversation_id uuid NOT NULL REFERENCES public.ig_conversations(id) ON DELETE CASCADE,
    user_id         uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    reply           text NOT NULL DEFAULT '',
    confidence      double precision,            -- 0..1 (jugement de couverture FAQ)
    needs_human     boolean NOT NULL DEFAULT false,
    reason          text,
    status          text NOT NULL DEFAULT 'pending', -- pending | approved | edited | rejected | sent
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ig_drafts_conversation_idx
    ON public.ig_drafts (conversation_id, created_at);

ALTER TABLE public.ig_drafts ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "Users manage own ig_drafts"
        ON public.ig_drafts FOR ALL
        USING (auth.uid() = user_id)
        WITH CHECK (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TABLE public.ig_conversations IS
    'Agent qualification Instagram — conversations prospects (ALE-195/201).';
COMMENT ON TABLE public.ig_messages IS
    'Agent qualification Instagram — messages in/out d''une conversation (ALE-195/201).';
COMMENT ON TABLE public.ig_drafts IS
    'Agent qualification Instagram — réponses suggérées par Claude (ALE-195/202).';
