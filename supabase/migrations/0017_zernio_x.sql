-- Colonnes Zernio pour la connexion X (Twitter).
-- Un profil Zernio est partagé LinkedIn + X (zernio_profile_id déjà en 0004).
-- On stocke uniquement l'accountId X et la date de connexion.

alter table public.user_editorial_profiles
  add column if not exists zernio_x_account_id text,
  add column if not exists zernio_x_connected_at timestamptz;
