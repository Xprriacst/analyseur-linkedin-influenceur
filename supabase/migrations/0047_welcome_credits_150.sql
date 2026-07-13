-- Migration 0047: offre de bienvenue portée de 60 → 150 crédits.
-- Le coût d'une analyse reste 20 crédits/influenceur (cf. CREDIT_COSTS backend) :
-- un nouveau compte passe donc de 3 à 7 analyses gratuites.
-- Trois emplacements du montant à aligner : le fallback Python (db.py, hors migration),
-- le défaut de la colonne, et l'auto-création dans debit_credits(). Idempotente.
--
-- Contrairement à la migration 0028 (20 → 60), les soldes EXISTANTS ne sont PAS
-- remontés : depuis l'arrivée de l'abonnement Stripe (0046), un bump aveugle
-- re-créditerait aussi les abonnés descendus sous le nouveau palier.

-- 1) Nouveau défaut de colonne (créations directes futures).
alter table public.user_credits alter column balance set default 150;

-- 2) Auto-création à 150 dans la fonction de débit : si la 1re action d'un
--    nouveau compte est une analyse, la ligne doit naître à 150 (pas 60).
--    Seul le littéral d'auto-création change vs migration 0028.
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
  -- Crée la ligne avec l'offre de bienvenue (150) si c'est la première visite
  insert into public.user_credits (user_id, balance)
  values (p_user_id, 150)
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

revoke execute on function public.debit_credits(uuid, integer, text, text) from public, anon, authenticated;
grant execute on function public.debit_credits(uuid, integer, text, text) to service_role;
