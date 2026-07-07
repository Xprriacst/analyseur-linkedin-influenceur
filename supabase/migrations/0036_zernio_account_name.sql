-- ALE-211 · Afficher le compte LinkedIn connecté dans le profil éditorial.
-- On mémorise, en plus de l'id technique du compte Zernio, son nom d'affichage
-- et (si Zernio l'expose) son type (profil personnel vs page entreprise), pour
-- que l'utilisateur sache sur quel compte partiront ses posts. Idempotente.

ALTER TABLE public.user_editorial_profiles
    ADD COLUMN IF NOT EXISTS zernio_account_name text,
    ADD COLUMN IF NOT EXISTS zernio_account_type text;

COMMENT ON COLUMN public.user_editorial_profiles.zernio_account_name IS
    'Nom d''affichage du compte LinkedIn connecté via Zernio (ALE-211).';
COMMENT ON COLUMN public.user_editorial_profiles.zernio_account_type IS
    'Type du compte LinkedIn connecté si Zernio l''expose (perso vs page pro) — ALE-211.';
