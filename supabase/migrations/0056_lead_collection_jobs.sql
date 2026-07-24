-- File d'attente serveur pour la collecte de commentateurs (ALE-240).
-- À exécuter dans le SQL editor du projet Supabase.
--
-- Même patron que image_generation_jobs (ALE-261, 0045) / generation_jobs
-- (ALE-141, 0023) : une ligne = une collecte des commentateurs d'un post
-- lead-magnet. L'état vit en base → le frontend peut fermer la pop-up / changer
-- d'onglet / rafraîchir, la collecte continue côté serveur et les leads sont
-- persistés à la fin.
--
-- Pourquoi une tâche de fond (avant, la collecte était synchrone) : le curseur
-- ALE-240 laisse récupérer bien plus que 100 commentateurs. Un gros post (1000+)
-- prend plusieurs minutes côté Apify — au-delà du budget d'une requête HTTP, qui
-- expirerait pendant que le scrape continue (et se facture) en silence.
--
-- Crédits : débités à la complétion réussie uniquement (jamais au lancement),
-- proportionnels au volume RÉELLEMENT récupéré — un échec ne coûte donc jamais
-- de crédit. Pré-check du solde (pire cas) fait AVANT de créer le job.
--
-- RLS : chaque utilisateur ne voit/écrit que ses propres jobs (auth.uid() = user_id).

create table if not exists public.lead_collection_jobs (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  source_id      uuid not null,
  post_url       text not null,
  max_comments   integer not null,
  status         text not null default 'queued',  -- queued | running | done | error | cancelled
  result         jsonb,   -- {comments_count, leads:{inserted,updated,skipped}, credits} une fois `done`
  error          text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists idx_lead_collection_jobs_user_created
  on public.lead_collection_jobs(user_id, created_at desc);

alter table public.lead_collection_jobs enable row level security;

drop policy if exists "own_lead_collection_jobs" on public.lead_collection_jobs;

create policy "own_lead_collection_jobs" on public.lead_collection_jobs
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Total de commentaires du post (lu au scrape d'import, `stats.comments`) : sert
-- à borner le curseur sur le vrai total plutôt qu'à l'aveugle, et à prévenir
-- l'utilisateur du volume disponible. Distinct de `comments_count`, qui compte
-- les commentaires RÉELLEMENT récupérés à la dernière collecte.
alter table public.lead_sources
  add column if not exists total_comments integer;
