-- Conversations persistantes pour l'assistant de génération de posts.
-- À exécuter dans le SQL editor du projet Supabase zcxaxwqkswuefzlzpgvi.
--
-- V1 : mémoire conversationnelle simple, sans outils. Chaque utilisateur ne voit
-- et n'écrit que ses conversations/messages (auth.uid() = user_id).

create table if not exists public.chat_conversations (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  title      text not null default 'Nouvelle conversation',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.chat_messages (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.chat_conversations(id) on delete cascade,
  user_id         uuid not null references auth.users(id) on delete cascade,
  role            text not null check (role in ('user', 'assistant')),
  content         text not null,
  created_at      timestamptz not null default now()
);

create index if not exists idx_chat_conversations_user_updated
  on public.chat_conversations(user_id, updated_at desc);

create index if not exists idx_chat_messages_conversation_created
  on public.chat_messages(conversation_id, created_at);

alter table public.chat_conversations enable row level security;
alter table public.chat_messages enable row level security;

grant select, insert, update, delete
  on public.chat_conversations
  to authenticated;

grant select, insert, update, delete
  on public.chat_messages
  to authenticated;

drop policy if exists "chat_conversations_select_own" on public.chat_conversations;
drop policy if exists "chat_conversations_insert_own" on public.chat_conversations;
drop policy if exists "chat_conversations_update_own" on public.chat_conversations;
drop policy if exists "chat_conversations_delete_own" on public.chat_conversations;

create policy "chat_conversations_select_own"
  on public.chat_conversations
  for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "chat_conversations_insert_own"
  on public.chat_conversations
  for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "chat_conversations_update_own"
  on public.chat_conversations
  for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "chat_conversations_delete_own"
  on public.chat_conversations
  for delete
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "chat_messages_select_own" on public.chat_messages;
drop policy if exists "chat_messages_insert_own" on public.chat_messages;
drop policy if exists "chat_messages_update_own" on public.chat_messages;
drop policy if exists "chat_messages_delete_own" on public.chat_messages;

create policy "chat_messages_select_own"
  on public.chat_messages
  for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "chat_messages_insert_own"
  on public.chat_messages
  for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1
      from public.chat_conversations c
      where c.id = conversation_id
        and c.user_id = (select auth.uid())
    )
  );

create policy "chat_messages_update_own"
  on public.chat_messages
  for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "chat_messages_delete_own"
  on public.chat_messages
  for delete
  to authenticated
  using ((select auth.uid()) = user_id);
