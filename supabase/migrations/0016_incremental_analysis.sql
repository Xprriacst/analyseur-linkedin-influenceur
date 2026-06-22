-- ALE-109 : cache global de classifications pour l'analyse incrémentale
-- Table cross-user (pas de user_id, pas de RLS) accessible via service-role uniquement.
-- Permet de réutiliser les classifications LLM déjà calculées pour un post, quel que soit
-- l'utilisateur qui l'a analysé en premier.

CREATE TABLE IF NOT EXISTS public.post_classification_cache (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    handle       text NOT NULL,
    platform     text NOT NULL DEFAULT 'linkedin',
    post_url     text NOT NULL,
    classification_json jsonb NOT NULL,
    created_at   timestamptz DEFAULT now(),
    CONSTRAINT post_classification_cache_unique UNIQUE (handle, platform, post_url)
);

-- Index pour les lookups par handle (requête d'incrémental = "donne-moi tous les posts de ce handle")
CREATE INDEX IF NOT EXISTS post_classification_cache_handle_idx
    ON public.post_classification_cache (handle, platform);

-- Pas de RLS sur cette table : accès service-role uniquement depuis le backend.
-- Le pipeline vérifie admin_enabled() avant tout accès.
