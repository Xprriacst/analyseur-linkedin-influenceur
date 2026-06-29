-- ALE-156 : post du jour généré à partir d'un lien d'annonce immobilière.
-- Quand une « idée » du réservoir (idea_seeds) est en réalité une URL d'annonce,
-- le cron lit l'annonce (image + infos) et génère un post ancré dessus, avec la
-- photo du bien. On stocke l'URL publique de la photo principale pour la rattacher
-- à la publication LinkedIn (chemin média Zernio existant, image passée en {url}).
-- Idempotente.

ALTER TABLE public.daily_ideas
  ADD COLUMN IF NOT EXISTS image_url text,
  ADD COLUMN IF NOT EXISTS source_url text;
