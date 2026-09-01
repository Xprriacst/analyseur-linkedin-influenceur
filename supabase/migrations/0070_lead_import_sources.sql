-- 0070 — Import d'une liste de leads depuis un fichier Excel/CSV.
--
-- Troisième nature de source de prospection, après les commentateurs d'un post
-- concurrent (0041/0056, kind='post') et l'import d'une recherche LinkedIn
-- (0062, kind='search') : un FICHIER de leads (export CRM, Sales Navigator via
-- un outil tiers, tableur maison) dont on extrait les URLs de profil.
--
-- On réutilise `lead_sources` / `lead_collection_jobs` (job de fond, polling,
-- dédup `save_leads`, scoring ICP) plutôt que de dupliquer la machinerie —
-- même choix que 0062. `post_url` porte une clé synthétique `import://{hash}`
-- dérivée du contenu du fichier : ré-importer LE MÊME fichier retombe sur la
-- même source (la contrainte d'unicité (user_id, post_url) fait la dédup) et
-- seuls les nouveaux profils s'ajoutent.
--
-- ⚠️ Aucune colonne nouvelle : seules les contraintes `kind` s'élargissent pour
-- accepter la valeur 'import'. Tant que cette migration n'est pas appliquée,
-- l'insert d'une source/d'un job kind='import' est refusé par la contrainte —
-- panne franche (l'endpoint renvoie une erreur), jamais silencieuse.
--
-- Idempotent (convention du repo) : rejouable sans effet de bord.

alter table public.lead_sources
  drop constraint if exists lead_sources_kind_check;
alter table public.lead_sources
  add constraint lead_sources_kind_check check (kind in ('post', 'search', 'import'));

alter table public.lead_collection_jobs
  drop constraint if exists lead_collection_jobs_kind_check;
alter table public.lead_collection_jobs
  add constraint lead_collection_jobs_kind_check check (kind in ('comments', 'search', 'import'));
