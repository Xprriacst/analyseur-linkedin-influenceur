-- Migration 0011: connexion X (Twitter) via Zernio (ALE-108)
-- Ajoute les colonnes pour mémoriser le compte X connecté,
-- calquées sur les colonnes LinkedIn de la migration 0004.

alter table public.user_editorial_profiles
  add column if not exists zernio_x_account_id text,
  add column if not exists zernio_x_connected_at timestamptz;
