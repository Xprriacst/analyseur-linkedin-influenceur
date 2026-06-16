-- Autorise l'upsert ALE-53 a remplacer l'analyse courante d'un influenceur.
-- Postgres execute un UPDATE lors du conflit (user_id, influencer_id), qui
-- necessite une policy RLS UPDATE explicite sur public.analyses.

drop policy if exists analyses_update_own on public.analyses;

create policy analyses_update_own
  on public.analyses
  for update
  to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
