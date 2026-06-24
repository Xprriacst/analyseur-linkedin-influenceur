-- ALE-136 : l'« idée du jour » devient un vrai post postable.
-- Le cron génère désormais un post complet (et non plus un concept d'idée).
-- On stocke le texte du post + ses métadonnées sur daily_ideas.
-- `idea_markdown` reste rempli (texte du post) pour la rétro-compatibilité des
-- lignes existantes. Idempotente.

ALTER TABLE public.daily_ideas
  ADD COLUMN IF NOT EXISTS post_text text,
  ADD COLUMN IF NOT EXISTS editorial_role text,
  ADD COLUMN IF NOT EXISTS hook_type text,
  ADD COLUMN IF NOT EXISTS strategy text,
  ADD COLUMN IF NOT EXISTS predicted_lift text;
