-- ALE-292 : connexion Instagram via Zernio (Mon profil → Connexions).
-- ⚠️ Numérotée 0058 (pas 0057) : la PR #380 (ALE-291 lots A+B) a déjà pris le
-- numéro 0057 et n'est pas encore mergée au moment où ce fichier est écrit.
--
-- Même patron que la connexion LinkedIn (0004_zernio.sql) : un compte Zernio
-- par plateforme, stocké sur le profil éditorial de l'utilisateur. Le
-- `zernio_profile_id` existant est réutilisé (1 profil Zernio par client,
-- toutes plateformes confondues).
--
-- Idempotente (rejouable).

alter table public.user_editorial_profiles
  add column if not exists zernio_instagram_account_id   text,
  add column if not exists zernio_instagram_account_name text,
  add column if not exists zernio_instagram_connected_at timestamptz;

comment on column public.user_editorial_profiles.zernio_instagram_account_id is
  'ALE-292 — id du compte Instagram (Business/Creator) connecté via Zernio.';
