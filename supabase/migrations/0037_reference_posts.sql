-- 0037 — Posts de référence (boîte à idées, ALE-67)
-- Posts trouvés ailleurs (LinkedIn ou autre) que l'utilisateur garde comme
-- inspiration. Injectés (échantillon) dans la génération de posts et d'idées :
-- l'IA peut s'inspirer de l'angle, de la structure ET du fond, mais réécrit
-- toujours — jamais de copier-coller.

create table if not exists public.user_reference_posts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  text text not null,
  url text,
  author text,
  note text,
  created_at timestamptz not null default now()
);

create index if not exists idx_user_reference_posts_user
  on public.user_reference_posts(user_id, created_at desc);

alter table public.user_reference_posts enable row level security;

grant select, insert, update, delete on public.user_reference_posts to authenticated;

drop policy if exists "users_own_reference_posts" on public.user_reference_posts;
create policy "users_own_reference_posts"
  on public.user_reference_posts
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
