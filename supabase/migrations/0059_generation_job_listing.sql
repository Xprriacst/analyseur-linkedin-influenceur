-- Fix : photo d'annonce perdue dans le parcours guidé (suite d'ALE-156/ALE-286).
--
-- Avant ALE-286, un lien d'annonce immobilière mis en idée de post passait par
-- l'« Idée du jour » : le sujet était réécrit sur le contenu de l'annonce et sa
-- photo (image_url/source_url sur daily_ideas) était rattachée au post. Le
-- parcours guidé (ALE-286), devenu le seul point d'entrée de génération, passait
-- l'URL brute au modèle et perdait la photo — silencieusement.
--
-- Ces deux colonnes portent la photo et le lien de l'annonce sur le JOB de
-- génération : le frontend rattache la photo au post produit, même si la page a
-- été quittée entre-temps (le job est la seule chose qui survit en base).
--
-- Idempotente (rejouable).

alter table public.generation_jobs
  add column if not exists listing_image_url  text,
  add column if not exists listing_source_url text;

comment on column public.generation_jobs.listing_image_url is
  'ALE-156 — URL publique de la photo principale de l''annonce quand le sujet du job était un lien d''annonce (rattachée au post généré par le frontend).';
comment on column public.generation_jobs.listing_source_url is
  'ALE-156 — URL de l''annonce d''origine (affichée sous la photo rattachée).';
