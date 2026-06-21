-- Migration 0008: système de crédits utilisateur (ALE-41)
-- user_credits : solde courant, 1 row par utilisateur
create table if not exists public.user_credits (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  balance integer not null default 20,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table public.user_credits enable row level security;

create policy "user_credits_select" on public.user_credits
  for select using (auth.uid() = user_id);

-- credit_ledger : journal d'audit de toutes les transactions
create table if not exists public.credit_ledger (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  action text not null,
  delta integer not null,        -- négatif = débit, positif = crédit
  balance_after integer not null,
  description text,
  created_at timestamptz default now()
);

alter table public.credit_ledger enable row level security;

create policy "credit_ledger_select" on public.credit_ledger
  for select using (auth.uid() = user_id);

-- Fonction atomique de débit (security definer = exécutée en tant que propriétaire)
-- Retourne le nouveau solde, lève une exception si insuffisant.
create or replace function public.debit_credits(
  p_user_id uuid,
  p_amount integer,
  p_action text,
  p_description text default null
) returns integer
language plpgsql
security definer
as $$
declare
  v_balance integer;
  v_new_balance integer;
begin
  -- Crée la ligne avec 20 crédits si c'est la première visite
  insert into public.user_credits (user_id, balance)
  values (p_user_id, 20)
  on conflict (user_id) do nothing;

  -- Verrouille la ligne pour éviter les courses concurrentes
  select balance into v_balance
  from public.user_credits
  where user_id = p_user_id
  for update;

  if v_balance < p_amount then
    raise exception 'INSUFFICIENT_CREDITS' using errcode = 'P0001';
  end if;

  v_new_balance := v_balance - p_amount;

  update public.user_credits
  set balance = v_new_balance, updated_at = now()
  where user_id = p_user_id;

  insert into public.credit_ledger (user_id, action, delta, balance_after, description)
  values (p_user_id, p_action, -p_amount, v_new_balance, p_description);

  return v_new_balance;
end;
$$;

-- Fonction d'ajout de crédits (admin / rechargement)
create or replace function public.add_credits(
  p_user_id uuid,
  p_amount integer,
  p_description text default 'rechargement'
) returns integer
language plpgsql
security definer
as $$
declare
  v_new_balance integer;
begin
  insert into public.user_credits (user_id, balance)
  values (p_user_id, p_amount)
  on conflict (user_id) do update
    set balance = public.user_credits.balance + p_amount,
        updated_at = now()
  returning balance into v_new_balance;

  insert into public.credit_ledger (user_id, action, delta, balance_after, description)
  values (p_user_id, 'add_credits', p_amount, v_new_balance, p_description);

  return v_new_balance;
end;
$$;

-- Sécurité : ces fonctions SECURITY DEFINER prennent p_user_id en paramètre.
-- Exposées en RPC PostgREST, un user authentifié pourrait s'auto-créditer (add_credits)
-- ou débiter le solde d'un autre user (debit_credits). On révoque donc l'EXECUTE par
-- défaut et on ne l'accorde qu'au service-role (le backend les appelle via admin_client()).
revoke execute on function public.debit_credits(uuid, integer, text, text) from public, anon, authenticated;
revoke execute on function public.add_credits(uuid, integer, text) from public, anon, authenticated;
grant execute on function public.debit_credits(uuid, integer, text, text) to service_role;
grant execute on function public.add_credits(uuid, integer, text) to service_role;
