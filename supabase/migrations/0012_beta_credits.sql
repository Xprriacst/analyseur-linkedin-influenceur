-- Migration 0012: helper d'activation du grant beta payant (ALE-107)
-- Permet à Alex de créditer 1 000 crédits d'un coup depuis le SQL editor Supabase
-- (pas exposé en HTTP — sécurité definer, accès service_role uniquement).

create or replace function public.grant_beta_paid_credits(
  p_email text,
  p_amount integer default 1000
) returns integer
language plpgsql
security definer
as $$
declare
  v_user_id uuid;
  v_new_balance integer;
begin
  select id into v_user_id
  from auth.users
  where email = p_email
  limit 1;

  if v_user_id is null then
    raise exception 'Utilisateur introuvable : %', p_email;
  end if;

  select public.add_credits(v_user_id, p_amount, 'beta_paid_grant') into v_new_balance;
  return v_new_balance;
end;
$$;

revoke execute on function public.grant_beta_paid_credits(text, integer) from public, anon, authenticated;
grant execute on function public.grant_beta_paid_credits(text, integer) to service_role;

comment on function public.grant_beta_paid_credits is
  'Attribue p_amount crédits (défaut 1000) au compte beta payant identifié par email.
   Appel depuis le SQL editor Supabase :
   select grant_beta_paid_credits(''client@example.com'');';
