-- 0031 — Ordre manuel des idées du réservoir (glisser-déposer).
-- L'utilisateur peut réordonner ses idées/annonces ; le cron (idée du jour,
-- posts hebdo) pioche désormais dans cet ordre plutôt qu'en FIFO strict.
-- Idempotent, rétro-compatible (colonne nullable ; on retombe sur created_at
-- pour les lignes sans position).

alter table public.idea_seeds
  add column if not exists position integer;

-- Backfill : on initialise la position des lignes existantes par utilisateur,
-- dans l'ordre historique (created_at) pour préserver l'ordre FIFO actuel.
update public.idea_seeds s
set position = ranked.rn
from (
  select id, row_number() over (partition by user_id order by created_at asc) - 1 as rn
  from public.idea_seeds
) ranked
where s.id = ranked.id
  and s.position is null;
