-- Agent Instagram — connexion ManyChat par utilisateur (multi-client).
-- Chaque utilisateur relie SON compte ManyChat : sa clé API (envoi) + une URL
-- de webhook personnelle (token) + un secret d'authentification (en-tête).
-- On réutilise la table générique `user_integrations` avec service = 'manychat' :
--   access_token  = clé API ManyChat du client (envoi des réponses)
--   webhook_token = slug public non devinable, sert à router un DM entrant
--                   vers le bon utilisateur (URL /manychat/webhooks/inbound/{token})
--   webhook_secret = vérifié dans l'en-tête X-ManyChat-Secret (authenticité)
-- Idempotente.

alter table public.user_integrations
  add column if not exists webhook_token text,
  add column if not exists webhook_secret text;

-- Routage du webhook entrant : lookup rapide + unicité du slug public.
create unique index if not exists idx_user_integrations_webhook_token
  on public.user_integrations(webhook_token)
  where webhook_token is not null;

comment on column public.user_integrations.webhook_token is
  'Slug public du webhook entrant par utilisateur (ManyChat) — route le DM vers le bon compte.';
comment on column public.user_integrations.webhook_secret is
  'Secret vérifié dans X-ManyChat-Secret pour authentifier le webhook entrant par utilisateur.';
