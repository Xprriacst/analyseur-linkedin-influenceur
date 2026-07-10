-- ALE-243 : curation manuelle des leads — statut « ne pas contacter » + raison.
-- Principe : on ne masque JAMAIS un lead. Ce statut sert seulement à reléguer un
-- lead écarté en bas de la liste (son score reste visible). Idempotent.

alter table public.leads
  add column if not exists contact_status text not null default 'to_contact';

alter table public.leads
  add column if not exists skip_reason text;

-- Contrainte de valeurs (ajout idempotent).
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'leads_contact_status_chk'
  ) then
    alter table public.leads
      add constraint leads_contact_status_chk
      check (contact_status in ('to_contact', 'skip'));
  end if;
end $$;
