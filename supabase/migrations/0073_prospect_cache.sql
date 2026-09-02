-- 0073 — vivier partagé de prospects (Mode Pilote)
-- Cartes publiques uniquement : URL de profil, nom, titre. PAS de user_id :
-- ce n'est pas la liste d'un compte, c'est un stock rempli par l'admin
-- (même idée qu'`influencer_cache` pour les comptes à suivre).
-- RLS ON, zéro policy : inaccessible à la clé anon. Service-role only.
-- Idempotente (IF NOT EXISTS).

create table if not exists public.prospect_cache (
  id           uuid primary key default gen_random_uuid(),
  profile_url  text not null,
  name         text,
  headline     text,
  created_at   timestamptz not null default now(),
  constraint prospect_cache_profile_url_unique unique (profile_url)
);

create index if not exists idx_prospect_cache_created
  on public.prospect_cache (created_at desc);

-- RLS activée sans aucune policy : refuse anon/authenticated (clé publique du
-- front). Seule la clé service-role (qui bypass la RLS) peut lire/écrire.
-- Sans ça, une table de `public` serait lisible par n'importe qui via
-- PostgREST + la clé anon — et le vivier est précisément ce qu'on ne veut
-- PAS exposer hors du backend.
alter table public.prospect_cache enable row level security;
