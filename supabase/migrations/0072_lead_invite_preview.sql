-- Accroche d'invitation générée (Mode Pilote). Persistée pour ne pas
-- re-payer un appel modèle à chaque ouverture de la vue du jour.
--
-- Le commentaire n'est PAS requis : un lead issu d'une recherche ou d'un
-- import n'en a pas. L'invitation LinkedIn reste SANS note (quotas) — ce
-- texte est l'aperçu du premier message, pas le corps de l'invitation.
--
-- Idempotente. Grants de `leads` au niveau table (0041) → la colonne est
-- couverte pour authenticated, rien à ajouter. Tant que la colonne manque
-- sur un env, `save_lead_invite_preview` échoue en best-effort : l'écran
-- retombe sur le gabarit, rien ne casse.

alter table public.leads
  add column if not exists invite_preview text;
