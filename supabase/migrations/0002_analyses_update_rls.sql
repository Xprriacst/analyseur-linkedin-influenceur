-- ALE-53 : upsert analyses exige une policy UPDATE (sinon relance → 42501 RLS).
drop policy if exists "analyses_update_own" on public.analyses;

create policy "analyses_update_own" on public.analyses
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
