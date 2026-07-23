-- 0055_onboarding_preview_events.sql
-- Suivi des analyses lancées depuis la landing (parcours anonyme /onboarding/draft).
-- Ces previews sont anonymes et n'étaient jamais persistées : impossible de compter
-- combien de visiteurs testent l'analyse avant de créer un compte. Cette table les
-- journalise (écriture service-role uniquement, aucun accès client).
-- Idempotente (IF NOT EXISTS).

create table if not exists public.onboarding_preview_events (
  id           uuid primary key default gen_random_uuid(),
  created_at   timestamptz not null default now(),
  input_kind   text,            -- 'linkedin' | 'website' | 'description'
  linkedin_url text,            -- URL/handle analysé (en clair, pour voir qui est testé)
  website_url  text,
  used_apify   boolean not null default false,  -- Apify a réellement renvoyé un profil
  preview_ok   boolean not null default false,  -- la preview « Analyse IA » a été générée
  ip_hash      text             -- SHA-256 tronqué de l'IP : dédoublonne les visiteurs
                                 -- sans stocker d'IP en clair
);

create index if not exists onboarding_preview_events_created_at_idx
  on public.onboarding_preview_events (created_at desc);

-- RLS activé + AUCUNE policy : la table est totalement inaccessible avec la clé anon
-- (client). Seule la clé service-role (qui bypass la RLS) peut écrire/lire.
alter table public.onboarding_preview_events enable row level security;
