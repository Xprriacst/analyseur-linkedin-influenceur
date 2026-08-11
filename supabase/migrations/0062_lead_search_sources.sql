-- 0062 — Import d'une recherche LinkedIn comme source de prospection.
--
-- Jusqu'ici une source de prospection était TOUJOURS un post concurrent dont on
-- récupérait les commentateurs (0041/0056). On ajoute une seconde nature de
-- source : un LIEN DE RECHERCHE LinkedIn (recherche classique, Sales Navigator,
-- recherche sauvegardée ou liste de leads) dont on récupère les profils via le
-- compte LinkedIn connecté du client (Unipile) — pagination réelle, coût
-- marginal nul (le forfait Unipile est par compte connecté, pas à l'usage).
--
-- On réutilise `lead_sources` / `lead_collection_jobs` plutôt que de dupliquer
-- toute la machinerie (job de fond, polling, dédup des leads, scoring ICP,
-- autopilote). D'où la colonne `kind` : sans elle, rien à l'écran ni en base ne
-- distinguerait un post d'une recherche, et le thread de collecte irait scraper
-- les « commentaires » d'une URL de recherche.
--
-- ⚠️ `lead_sources.post_url` porte l'URL de recherche pour une source `search`
-- (la contrainte d'unicité (user_id, post_url) sert alors de dédup naturelle :
-- ré-importer la même recherche relance la collecte au lieu de créer un doublon).
--
-- Idempotent (convention du repo) : rejouable sans effet de bord.

alter table public.lead_sources
  add column if not exists kind text not null default 'post';

alter table public.lead_sources
  drop constraint if exists lead_sources_kind_check;
alter table public.lead_sources
  add constraint lead_sources_kind_check check (kind in ('post', 'search'));

-- Total annoncé par LinkedIn pour la recherche (`paging.total_count`). Distinct
-- de `comments_count`, qui compte les profils RÉELLEMENT récupérés à la dernière
-- collecte. Sert à borner le curseur sur le vrai volume disponible.
-- ⚠️ LinkedIn ne restitue jamais plus de 1000 profils par recherche (2500 en
-- Sales Navigator) même quand ce total en annonce davantage.
alter table public.lead_sources
  add column if not exists search_total integer;

alter table public.lead_collection_jobs
  add column if not exists kind text not null default 'comments';

alter table public.lead_collection_jobs
  drop constraint if exists lead_collection_jobs_kind_check;
alter table public.lead_collection_jobs
  add constraint lead_collection_jobs_kind_check check (kind in ('comments', 'search'));

-- Identifiant LinkedIn interne du lead (format `ACoAA…`). La recherche Unipile
-- le renvoie déjà : le stocker à l'import évite un appel de résolution de profil
-- par lead au moment de l'invitation. La colonne existe depuis 0043 (ALE-230) —
-- ce `if not exists` ne fait que garantir la présence sur une base repartie de zéro.
alter table public.leads
  add column if not exists provider_id text;
