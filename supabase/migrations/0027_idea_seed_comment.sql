-- 0027 — Commentaire d'orientation sur les idées du réservoir (annonces immobilières).
-- Quand une idée est un lien d'annonce, l'utilisateur peut joindre un court
-- commentaire pour orienter le post généré (ex. « insiste sur la vue mer »).
-- Idempotent, rétro-compatible (colonne nullable, aucune valeur par défaut requise).

alter table public.idea_seeds
  add column if not exists comment text;
