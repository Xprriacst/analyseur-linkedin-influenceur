-- 0054 — Photos de soi pour génération d'image IA
-- L'utilisateur uploade jusqu'à 5 photos de lui dans Mon profil ; l'IA (GPT Image 2)
-- s'en sert comme références d'identité pour le placer dans le contexte d'un post.
-- Stockage = URL publique (upload Zernio, même patron que les images de posts).
-- RLS : chaque utilisateur ne voit/écrit que ses propres photos.

create table if not exists public.user_self_photos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  image_url text not null,
  filename text,
  created_at timestamptz not null default now()
);

create index if not exists idx_user_self_photos_user_created
  on public.user_self_photos(user_id, created_at desc);

alter table public.user_self_photos enable row level security;

grant select, insert, delete on public.user_self_photos to authenticated;
-- Pas d'UPDATE côté client : une photo se remplace en delete + insert.

drop policy if exists "own_user_self_photos" on public.user_self_photos;
create policy "own_user_self_photos" on public.user_self_photos
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Le job d'image peut porter 1 à N photos de soi (jsonb = liste d'uuid).
-- Mutuellement exclusif côté API avec reference_template_id (style bibliothèque).
alter table public.image_generation_jobs
  add column if not exists reference_self_photo_ids jsonb not null default '[]'::jsonb;
