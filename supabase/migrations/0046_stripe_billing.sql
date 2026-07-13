-- Migration 0046: abonnement Stripe (ALE-274) — 49 €/mois = 1000 crédits.
-- Idempotente / rejouable.
--
-- Trois briques :
--   1. user_subscriptions : état d'abonnement par compte (client + abonnement Stripe).
--   2. billing_events     : journal des événements Stripe déjà traités (idempotence
--                           du webhook — Stripe rejoue un événement jusqu'à ce qu'il
--                           reçoive un 2xx, sans dédoublonnage on créditerait 2 fois).
--   3. set_credits()      : fixe le solde à une valeur (pas d'incrément). Décision
--                           produit : les crédits non consommés ne sont PAS reportés,
--                           le solde repart à 1000 à chaque facture payée.

-- ── 1. État d'abonnement ── --
create table if not exists public.user_subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  stripe_customer_id text unique,
  stripe_subscription_id text unique,
  status text,                       -- active | trialing | past_due | canceled | incomplete…
  price_id text,
  cancel_at_period_end boolean not null default false,
  current_period_end timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.user_subscriptions enable row level security;

-- Lecture seule côté client : seul le backend (service-role, via le webhook Stripe)
-- écrit — un utilisateur ne doit jamais pouvoir se déclarer abonné.
drop policy if exists "user_subscriptions_select" on public.user_subscriptions;
create policy "user_subscriptions_select" on public.user_subscriptions
  for select using (auth.uid() = user_id);

create index if not exists user_subscriptions_customer_idx
  on public.user_subscriptions (stripe_customer_id);

-- ── 2. Idempotence du webhook ── --
create table if not exists public.billing_events (
  id text primary key,               -- id de l'événement Stripe (evt_…)
  type text,
  user_id uuid references auth.users(id) on delete set null,
  created_at timestamptz default now()
);

alter table public.billing_events enable row level security;
-- Aucune policy : table purement serveur (service-role bypasse la RLS).

-- ── 3. Fixer le solde (renouvellement d'abonnement) ── --
-- Ne PAS incrémenter : le solde est remis à p_amount. Le mouvement est journalisé
-- dans credit_ledger avec le delta réel (positif ou négatif) pour garder l'audit
-- cohérent avec debit_credits()/add_credits().
create or replace function public.set_credits(
  p_user_id uuid,
  p_amount integer,
  p_action text default 'subscription_renewal',
  p_description text default null
) returns integer
language plpgsql
security definer
as $$
declare
  v_old_balance integer;
begin
  insert into public.user_credits (user_id, balance)
  values (p_user_id, p_amount)
  on conflict (user_id) do nothing;

  select balance into v_old_balance
  from public.user_credits
  where user_id = p_user_id
  for update;

  update public.user_credits
  set balance = p_amount, updated_at = now()
  where user_id = p_user_id;

  insert into public.credit_ledger (user_id, action, delta, balance_after, description)
  values (p_user_id, p_action, p_amount - coalesce(v_old_balance, 0), p_amount, p_description);

  return p_amount;
end;
$$;

-- Même posture de sécurité que debit_credits()/add_credits() (migration 0008) :
-- SECURITY DEFINER + p_user_id en paramètre ⇒ un utilisateur authentifié pourrait
-- se fixer 1000 crédits. Réservé au service-role (le backend l'appelle depuis le
-- webhook Stripe, jamais depuis une requête portant un JWT utilisateur).
revoke execute on function public.set_credits(uuid, integer, text, text) from public, anon, authenticated;
grant execute on function public.set_credits(uuid, integer, text, text) to service_role;
