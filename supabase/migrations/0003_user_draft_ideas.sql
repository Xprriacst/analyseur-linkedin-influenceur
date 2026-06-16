-- Brouillons d'idees utilisateur reutilises comme contexte par le generateur.
-- A executer dans le SQL editor du projet Supabase zcxaxwqkswuefzlzpgvi.
--
-- RLS : chaque utilisateur ne voit et ne modifie que ses propres brouillons.

create table if not exists public.user_draft_ideas (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  text       text not null check (char_length(trim(text)) > 0),
  used_at    timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_user_draft_ideas_user_created
  on public.user_draft_ideas(user_id, created_at desc);

create index if not exists idx_user_draft_ideas_user_active
  on public.user_draft_ideas(user_id, created_at desc)
  where used_at is null;

alter table public.user_draft_ideas enable row level security;

drop policy if exists "own_draft_ideas" on public.user_draft_ideas;

create policy "own_draft_ideas" on public.user_draft_ideas
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
