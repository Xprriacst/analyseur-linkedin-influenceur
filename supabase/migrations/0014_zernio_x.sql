-- ALE-108 : colonnes Zernio pour X (Twitter) sur user_editorial_profiles
-- Même structure que les colonnes LinkedIn (migration 0004_zernio.sql).

ALTER TABLE public.user_editorial_profiles
  ADD COLUMN IF NOT EXISTS zernio_x_account_id  text,
  ADD COLUMN IF NOT EXISTS zernio_x_connected_at timestamptz;
