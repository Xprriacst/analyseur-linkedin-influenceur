-- ALE-59 : publication multi-réseaux (X + Reddit) depuis la pop-up de publication.
--
-- 1) Connexion Reddit via Zernio : même modèle que X (0017) — le profil Zernio
--    est partagé (zernio_profile_id, 0004), on ne stocke que l'accountId Reddit.
-- 2) Versions adaptées stockées avec le post programmé : `cross_posts` jsonb
--    ({"x": {"tweets": [...]}, "reddit": {"title", "subreddit", "body", ...}}).
--    Le cron de publication (src/scheduler.py) publie ces versions au même
--    créneau que le post LinkedIn et y consigne le résultat par réseau.
-- Idempotente.

alter table public.user_editorial_profiles
  add column if not exists zernio_reddit_account_id text,
  add column if not exists zernio_reddit_connected_at timestamptz;

alter table public.scheduled_posts
  add column if not exists cross_posts jsonb not null default '{}'::jsonb;
