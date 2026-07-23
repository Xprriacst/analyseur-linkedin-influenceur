-- Retry des posts programmés en échec (cron + bouton « Réessayer »).
-- Sans compteur, un post en panne permanente (compte LinkedIn déconnecté…)
-- restait `failed` à jamais — le client devait reprogrammer à la main.
-- Idempotente.

alter table public.scheduled_posts
  add column if not exists publish_attempts integer not null default 0;

comment on column public.scheduled_posts.publish_attempts is
  'Nombre de tentatives de publication par le cron / retry manuel. Plafond soft côté code.';
