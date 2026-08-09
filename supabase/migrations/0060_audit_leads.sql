-- 0060_audit_leads.sql
-- Tunnel « audit complet gratuit » de la landing : le visiteur voit son audit léger,
-- puis laisse nom / e-mail / téléphone pour recevoir l'audit complet par e-mail et
-- prendre rendez-vous (Calendly).
--
-- Contrairement à `onboarding_preview_events` (comptage anonyme des analyses), cette
-- table porte des DONNÉES PERSONNELLES nominatives : elle est donc, comme la 0055,
-- en RLS activé SANS aucune policy → totalement inaccessible avec la clé anon du
-- navigateur. Seule la clé service-role (backend / cron) peut lire et écrire.
-- Idempotente (IF NOT EXISTS).

create table if not exists public.audit_leads (
  id             uuid primary key default gen_random_uuid(),
  created_at     timestamptz not null default now(),

  -- Ce que le visiteur a laissé (les 3 champs sont obligatoires côté API).
  full_name      text not null,
  email          text not null,
  phone          text not null,

  -- Ce sur quoi porte l'audit.
  linkedin_url   text,
  website_url    text,
  input_kind     text,          -- 'linkedin' | 'website' | 'description'

  -- Instantané de l'audit léger déjà affiché au visiteur + réponses de l'onboarding.
  -- Stocké tel quel : c'est la matière première de l'audit complet, et la preview
  -- coûte un scrape Apify + un appel Claude — la refaire à l'envoi serait payer deux fois.
  preview        jsonb,
  profile        jsonb,
  projection     jsonb,         -- gains projetés affichés à l'écran (traçabilité de la promesse)

  -- Cycle de vie de l'envoi de l'audit complet (lot 2 : génération + e-mail).
  status         text not null default 'pending',   -- pending | generating | sent | failed
  audit_payload  jsonb,
  error_message  text,
  sent_at        timestamptz,

  consent        boolean not null default false,
  ip_hash        text            -- SHA-256 tronqué : dédoublonne sans stocker d'IP en clair
);

create index if not exists audit_leads_created_at_idx on public.audit_leads (created_at desc);
create index if not exists audit_leads_email_idx on public.audit_leads (lower(email));
create index if not exists audit_leads_status_idx on public.audit_leads (status);

alter table public.audit_leads enable row level security;
