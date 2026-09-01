-- Pool partagé de prospects — Mode Pilote (ticket Notion « Agent prospects »,
-- décision Alex 2026-09-01) : chaque jour, ≤3 prospects proposés à un compte
-- SANS LinkedIn connecté, piochés dans les leads identifiés par les AUTRES
-- comptes. Cette table est le mémo des attributions du jour ET le verrou de
-- réservation.
--
-- ⚠️ Frontière d'anonymisation : la ligne ne porte QUE les données publiques du
-- profil (nom, headline, URL LinkedIn) — jamais le commentaire, le score ICP ni
-- aucun contexte du compte source (cf. src/prospect_pool.py, deux remparts
-- testés). Ne pas ajouter de colonne « privée » ici.
--
-- Cross-user par nature (le pool lit les leads de tous les comptes) :
-- service-role only — RLS active, AUCUNE policy (patron audit_leads /
-- onboarding_preview_events / lead_notifications). La lecture côté client passe
-- par GET /me/pilot/today, qui ne sert que les attributions du compte appelant.

create table if not exists public.pilot_pool_assignments (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  day date not null,
  profile_url text not null,
  name text,
  headline text,
  position integer not null default 0,
  created_at timestamptz not null default now()
);

-- Réservation : un prospect n'est proposé qu'à UN compte par jour. L'index
-- unique est le verrou (pas un select préalable) — deux comptes qui ouvrent
-- l'app au même instant ne peuvent pas se voir attribuer la même personne :
-- l'insert du second échoue et le code passe au candidat suivant.
create unique index if not exists pilot_pool_assignments_day_prospect_key
  on public.pilot_pool_assignments (day, profile_url);

-- Relecture du mémo du jour (à chaque ouverture du Mode Pilote).
create index if not exists pilot_pool_assignments_user_day_idx
  on public.pilot_pool_assignments (user_id, day);

-- Historique par compte : un prospect déjà proposé ne revient pas.
create index if not exists pilot_pool_assignments_user_prospect_idx
  on public.pilot_pool_assignments (user_id, profile_url);

alter table public.pilot_pool_assignments enable row level security;
