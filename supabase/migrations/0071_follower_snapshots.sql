-- Mon profil → Dashboard : baseline + progression d'abonnés (backlog Notion,
-- priorité Alex 2026-08-31). À exécuter dans le SQL editor Supabase.
--
-- Une ligne = un relevé quotidien du nombre d'abonnés du client sur son PROPRE
-- compte LinkedIn (jamais celui d'un influenceur suivi). Le relevé n'est JAMAIS
-- produit par un scrape déclenché depuis ce dashboard (coût Apify) : c'est un
-- point d'historique posé, best-effort, sur la valeur déjà connue dans le corpus
-- du client (`influencers.follower_count`, sur le handle de son `linkedin_url`
-- de profil éditorial). Sans profil analysé, il n'y a simplement rien à
-- enregistrer — la table peut rester vide pour un compte, ce n'est pas une erreur.
--
-- Idempotent PAR JOUR : `unique(user_id, captured_on)` + upsert côté app
-- (`db.record_follower_snapshot`) — ouvrir le dashboard plusieurs fois la même
-- journée ne crée qu'une ligne, mise à jour avec la dernière valeur connue.
--
-- RLS : chaque utilisateur ne voit/écrit que ses propres relevés (auth.uid() = user_id),
-- même patron que `lead_collection_jobs` (0056).

create table if not exists public.user_follower_snapshots (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  captured_on    date not null,
  follower_count integer not null,
  source         text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique (user_id, captured_on)
);

create index if not exists idx_user_follower_snapshots_user_captured
  on public.user_follower_snapshots(user_id, captured_on);

alter table public.user_follower_snapshots enable row level security;

drop policy if exists "own_follower_snapshots" on public.user_follower_snapshots;

create policy "own_follower_snapshots" on public.user_follower_snapshots
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
