-- ALE-107 : fonction SQL pour créditer les clients payants beta
-- Usage depuis le SQL editor Supabase :
--   select grant_beta_paid_credits('client@example.com');
--   select grant_beta_paid_credits('client@example.com', 500);  -- montant personnalisé
create or replace function public.grant_beta_paid_credits(
  p_email text,
  p_amount int default 1000
) returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_user_id uuid;
  v_old_balance int := 0;
  v_new_balance int;
begin
  select id into v_user_id from auth.users where email = p_email;
  if v_user_id is null then
    return 'Utilisateur introuvable : ' || p_email;
  end if;

  select balance into v_old_balance
  from public.user_credits
  where user_id = v_user_id;

  v_new_balance := coalesce(v_old_balance, 0) + p_amount;

  insert into public.user_credits (user_id, balance)
  values (v_user_id, v_new_balance)
  on conflict (user_id) do update
    set balance = excluded.balance,
        updated_at = now();

  return 'OK — ' || p_amount || ' crédits accordés à ' || p_email
    || ' (ancien solde : ' || coalesce(v_old_balance, 0)
    || ', nouveau : ' || v_new_balance || ')';
end;
$$;
