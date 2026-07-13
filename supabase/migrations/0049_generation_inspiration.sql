-- ALE-286 : post d'inspiration porté par le job de génération.
--
-- Le parcours « J'ai une inspiration » laisse le client coller le lien d'un post
-- LinkedIn : on le lit, puis ce post sert de RÉFÉRENCE à la génération (angle,
-- structure, fond — toujours réécrits, jamais copiés : c'est la règle déjà en
-- vigueur pour les posts de référence de la bibliothèque).
--
-- Pourquoi le stocker sur le job plutôt que de le passer au thread : la
-- génération tourne en arrière-plan et relit sa ligne en base. Un texte passé
-- seulement en mémoire disparaîtrait au moindre redémarrage du service (ce qui
-- arrive régulièrement sur Render) et le post serait généré SANS son
-- inspiration, sans la moindre erreur visible — exactement le genre de panne
-- silencieuse qu'on cherche à éviter.
--
-- Idempotente (rejouable).

alter table public.generation_jobs
  add column if not exists inspiration_text   text,
  add column if not exists inspiration_author text,
  add column if not exists inspiration_url    text;

comment on column public.generation_jobs.inspiration_text is
  'ALE-286 — texte du post LinkedIn dont le client veut s''inspirer (injecté comme post de référence à la génération).';
