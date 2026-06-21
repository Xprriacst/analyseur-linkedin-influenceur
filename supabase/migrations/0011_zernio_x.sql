-- ALE-108 : colonnes Zernio X (Twitter) sur user_editorial_profiles
alter table public.user_editorial_profiles
  add column if not exists zernio_x_account_id text,
  add column if not exists zernio_x_connected_at timestamptz;
