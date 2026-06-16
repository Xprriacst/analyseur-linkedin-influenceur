-- Bibliotheque persistante des outputs IA : idees et posts generes.
-- A executer dans le SQL editor du projet Supabase zcxaxwqkswuefzlzpgvi.
--
-- RLS : chaque utilisateur ne voit/ecrit que ses propres generations.

create table if not exists public.generated_ideas (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid not null references auth.users(id) on delete cascade,
  title               text,
  angle               text,
  hook                text,
  hook_type           text,
  funnel              text,
  why_it_works        text,
  difficulty          text,
  estimated_lift      text,
  status              text not null default 'saved'
    check (status in ('draft', 'saved', 'validated', 'archived')),
  source_ideas_run_id uuid,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create table if not exists public.generated_posts (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references auth.users(id) on delete cascade,
  idea_id           uuid references public.generated_ideas(id) on delete set null,
  topic             text,
  post_text         text not null,
  hook_type         text,
  strategy          text,
  predicted_lift    text,
  variant_index     int,
  status            text not null default 'draft'
    check (status in ('draft', 'ready', 'published', 'archived')),
  published_at      timestamptz,
  linkedin_post_url text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists idx_generated_ideas_user_created
  on public.generated_ideas(user_id, created_at desc);
create index if not exists idx_generated_ideas_user_status
  on public.generated_ideas(user_id, status);
create index if not exists idx_generated_posts_user_created
  on public.generated_posts(user_id, created_at desc);
create index if not exists idx_generated_posts_user_status
  on public.generated_posts(user_id, status);
create index if not exists idx_generated_posts_idea
  on public.generated_posts(idea_id);

alter table public.generated_ideas enable row level security;
alter table public.generated_posts enable row level security;

drop policy if exists "own_generated_ideas" on public.generated_ideas;
drop policy if exists "own_generated_posts" on public.generated_posts;

create policy "own_generated_ideas" on public.generated_ideas
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "own_generated_posts" on public.generated_posts
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
