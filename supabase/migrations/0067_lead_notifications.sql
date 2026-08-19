-- Notifications e-mail « nouveau lead » : journal de ce qui a DÉJÀ été envoyé.
--
-- Raison d'être : la détection des nouveaux comptes se fait par balayage
-- périodique (le serveur n'est prévenu par personne quand quelqu'un s'inscrit —
-- l'inscription se joue entre le navigateur et Supabase Auth). Sans trace de ce
-- qui est parti, chaque passage du cron ré-enverrait le même lead toutes les
-- 10 minutes. L'index unique est le verrou : c'est lui qui rend l'envoi
-- exactement-une-fois, pas la bonne volonté du code appelant.
--
-- Service-role only (RLS active, AUCUNE policy) — patron de `audit_leads`.

create table if not exists public.lead_notifications (
  id uuid primary key default gen_random_uuid(),
  kind text not null,          -- 'signup' | 'optin' | 'subscription'
  ref text not null,           -- user_id, e-mail, ou id d'événement Stripe
  notified_at timestamptz not null default now()
);

create unique index if not exists lead_notifications_kind_ref_key
  on public.lead_notifications (kind, ref);

create index if not exists lead_notifications_notified_at_idx
  on public.lead_notifications (notified_at desc);

alter table public.lead_notifications enable row level security;
