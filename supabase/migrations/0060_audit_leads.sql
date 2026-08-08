-- 0060_audit_leads.sql
-- Leads « audit complet gratuit » capturés à la fin de l'audit léger de la landing
-- (parcours anonyme /start). Le visiteur laisse nom + email + téléphone pour recevoir
-- son audit complet par e-mail, puis part sur le Calendly de Tom.
-- Écriture service-role uniquement (même patron que onboarding_preview_events, 0055) :
-- RLS activé + AUCUNE policy = table invisible avec la clé anon côté client.
-- Idempotente (IF NOT EXISTS).

create table if not exists public.audit_leads (
  id            uuid primary key default gen_random_uuid(),
  created_at    timestamptz not null default now(),
  name          text not null,
  email         text not null,
  phone         text not null,
  linkedin_url  text,            -- profil analysé par l'audit léger (en clair)
  input_kind    text,            -- 'linkedin' | 'website' | 'description'
  preview       jsonb,           -- snapshot de l'analyse légère (ancre l'audit complet)
  profile_draft jsonb,           -- brouillon de profil éditorial déduit par l'IA
  audit         jsonb,           -- pack semi-personnalisé généré (relisible/renvoyable)
  -- 'received' → 'sent' | 'failed' | 'email_disabled' (RESEND_API_KEY absente :
  -- le lead est quand même capturé, l'email partira d'un renvoi manuel).
  status        text not null default 'received',
  email_error   text,
  ip_hash       text             -- SHA-256 tronqué de l'IP (dédoublonnage, pas d'IP en clair)
);

create index if not exists audit_leads_created_at_idx
  on public.audit_leads (created_at desc);

alter table public.audit_leads enable row level security;
