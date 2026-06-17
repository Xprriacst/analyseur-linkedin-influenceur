-- Mapping vers Zernio (publication LinkedIn) pour chaque utilisateur.
-- Une cle API Zernio unique (cote serveur) ; un "profile" Zernio par utilisateur ;
-- un compte LinkedIn connecte via OAuth dont on memorise l'accountId.

alter table public.user_editorial_profiles
  add column if not exists zernio_profile_id text,
  add column if not exists zernio_account_id text,
  add column if not exists zernio_connected_at timestamptz;
