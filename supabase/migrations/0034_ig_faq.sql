-- Agent qualification Instagram — FAQ + objectif éditables par l'utilisateur.
-- Remplace le fichier de config serveur (IG_FAQ_PATH) comme source principale :
-- le cerveau lit d'abord la FAQ de l'utilisateur en base, sinon retombe sur le fichier.
-- Idempotente (IF NOT EXISTS). RLS auth.uid() = user_id.

CREATE TABLE IF NOT EXISTS public.ig_faqs (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    content    text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.ig_faqs ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "Users manage own ig_faqs"
        ON public.ig_faqs FOR ALL
        USING (auth.uid() = user_id)
        WITH CHECK (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TABLE public.ig_faqs IS
    'Agent qualification Instagram — FAQ + objectif remplis par l''utilisateur (source de vérité du cerveau).';
