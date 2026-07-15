-- ALE-174 (suite) : détection automatique de l'acceptation des invitations.
-- Le moteur balaie les leads en « invitation envoyée » et bascule ceux qui ont
-- accepté. `outreach_last_checked_at` cadence ce balayage (dernier re-check), sans
-- se confondre avec `outreach_updated_at` qui ne bouge qu'au changement de STATUT.
-- Écrit uniquement par le cron (service-role) ; le client n'a pas à l'écrire.
-- Idempotent.

alter table public.leads
  add column if not exists outreach_last_checked_at timestamptz;
