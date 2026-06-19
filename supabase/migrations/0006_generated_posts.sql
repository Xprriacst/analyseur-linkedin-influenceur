-- Posts générés persistés par utilisateur (auto-sauvegarde à la génération).
-- Pendant des `generated_ideas` ; un variant = une ligne.
-- `generated_ideas` est recréée ici en `if not exists` pour que le repo soit
-- auto-suffisant (la table existait déjà en base, créée manuellement).

create table if not exists public.generated_ideas (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text,
  hook text,
  hook_type text,
  funnel text,
  angle text,
  why_it_works text,
  difficulty text,
  estimated_lift text,
  created_at timestamptz default now()
);

create table if not exists public.generated_posts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  topic text,
  editorial_role text,
  hook_type text,
  strategy text,
  predicted_lift text,
  post text not null,
  created_at timestamptz default now()
);

create index if not exists idx_generated_ideas_user
  on public.generated_ideas(user_id, created_at desc);
create index if not exists idx_generated_posts_user
  on public.generated_posts(user_id, created_at desc);

alter table public.generated_ideas enable row level security;
alter table public.generated_posts enable row level security;

grant select, insert, update, delete on public.generated_ideas to authenticated;
grant select, insert, update, delete on public.generated_posts to authenticated;

drop policy if exists "users_own_ideas" on public.generated_ideas;
create policy "users_own_ideas"
  on public.generated_ideas
  for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists "users_own_posts" on public.generated_posts;
create policy "users_own_posts"
  on public.generated_posts
  for all
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
