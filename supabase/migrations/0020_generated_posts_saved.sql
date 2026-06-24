-- ALE-134 : notion de post « sauvegardé » sur generated_posts.
-- Les posts générés sont auto-insérés à la génération (db.save_generated_posts).
-- Désormais seuls les posts marqués `saved = true` apparaissent dans « Mes contenus » (ALE-135).
-- Idempotente.

-- On ajoute la colonne avec DEFAULT true : les posts DÉJÀ présents sont backfillés
-- à true (ils restent visibles dans la librairie existante)...
ALTER TABLE public.generated_posts
  ADD COLUMN IF NOT EXISTS saved boolean NOT NULL DEFAULT true;

-- ...puis on bascule le défaut à false : les NOUVEAUX posts auto-sauvegardés
-- naissent non-sauvegardés et n'apparaissent dans la librairie qu'après un clic
-- explicite sur « Sauvegarder ».
ALTER TABLE public.generated_posts
  ALTER COLUMN saved SET DEFAULT false;
