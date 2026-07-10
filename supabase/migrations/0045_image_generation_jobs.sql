-- File d'attente serveur pour la génération d'image IA (ALE-261).
-- À exécuter dans le SQL editor du projet Supabase.
--
-- Même patron que generation_jobs (ALE-141, 0023) : une ligne = une génération
-- d'image, résultat stocké en jsonb une fois terminée. L'état vit en base → le
-- frontend peut fermer la pop-up / changer d'onglet / rafraîchir, la génération
-- continue côté serveur et le résultat est conservé.
--
-- `target_key` est un identifiant opaque côté client qui désigne le bloc de
-- post auquel l'image doit se rattacher (ex. "variant:2", "saved:<uuid>",
-- "idea:<uuid>", "chat:<conversation_id>:<message_index>") : c'est ce qui
-- permet à l'image de rejoindre le BON post même après fermeture de la pop-up.
--
-- Crédits : débités à la complétion réussie uniquement (jamais au lancement) —
-- un échec ne coûte donc jamais de crédit, pas de remboursement à gérer.
--
-- RLS : chaque utilisateur ne voit/écrit que ses propres jobs (auth.uid() = user_id).

create table if not exists public.image_generation_jobs (
  id                     uuid primary key default gen_random_uuid(),
  user_id                uuid not null references auth.users(id) on delete cascade,
  status                 text not null default 'queued',  -- queued | running | done | error | cancelled
  post_text              text not null,
  prompt                 text,
  reference_template_id  uuid,
  target_key             text not null,
  result                 jsonb,   -- {image_data, prompt_used, credits} une fois `done`
  error                  text,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);

create index if not exists idx_image_generation_jobs_user_created
  on public.image_generation_jobs(user_id, created_at desc);

alter table public.image_generation_jobs enable row level security;

drop policy if exists "own_image_generation_jobs" on public.image_generation_jobs;

create policy "own_image_generation_jobs" on public.image_generation_jobs
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
