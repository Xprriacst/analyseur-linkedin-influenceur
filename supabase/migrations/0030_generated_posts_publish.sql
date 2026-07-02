-- Publication LinkedIn des posts envoyés directement en validation Slack.
-- Jusqu'ici, valider un post « envoi direct » ne faisait que passer
-- slack_status='validated' sans rien publier (contrairement aux scheduled_posts
-- que le cron publie). On ajoute la trace de la publication Zernio pour rendre
-- le clic « Valider » = publication immédiate, et garantir l'idempotence
-- (ne pas republier si Slack rejoue la webhook).
-- Idempotente, rétro-compatible (défaut = NULL tant que non publié).

alter table public.generated_posts
  add column if not exists zernio_post_id text;
