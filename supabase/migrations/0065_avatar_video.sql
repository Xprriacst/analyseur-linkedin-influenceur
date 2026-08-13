-- 0065 : avatar IA vidéo (HeyGen) — l'avatar du client + la file de rendus.
--
-- Le client crée SON photo avatar HeyGen depuis Mon profil → Connexions (une
-- photo suffit, pas de consentement HeyGen sur ce type d'avatar) ; le look_id
-- et la voix choisie vivent sur user_editorial_profiles (patron des colonnes
-- zernio_*). La génération d'une vidéo (l'avatar dit le script du pack Reel)
-- passe par une file de jobs de fond, patron image_generation_jobs (0045) :
-- lancer puis fermer la pop-up, le résultat rejoint la ligne via target_key.
--
-- ⚠️ result ne porte QUE des URLs (vidéo re-hébergée Zernio, miniature) et des
-- scalaires — JAMAIS d'octets ni de base64 : leçon de l'OOM du 2026-07-27
-- (image_generation_jobs.result à 1,3-2 Mo pollé toutes les 3 s a tué la prod).
-- C'est aussi pourquoi la liste peut ici projeter result sans danger.
--
-- Débit des crédits à la complétion réussie uniquement (jamais au lancement),
-- comme les images — aucun remboursement à gérer.

alter table public.user_editorial_profiles
  add column if not exists heygen_avatar_look_id text,
  add column if not exists heygen_avatar_group_id text,
  add column if not exists heygen_avatar_status text,
  add column if not exists heygen_avatar_preview_url text,
  add column if not exists heygen_avatar_created_at timestamptz,
  add column if not exists heygen_voice_id text,
  add column if not exists heygen_voice_name text;

comment on column public.user_editorial_profiles.heygen_avatar_look_id is
  'Identifiant du look photo avatar HeyGen du client (POST /v3/avatars). NULL = pas d''avatar.';
comment on column public.user_editorial_profiles.heygen_avatar_status is
  'Statut normalisé de l''entraînement : processing | completed | failed.';
comment on column public.user_editorial_profiles.heygen_voice_id is
  'Voix stock HeyGen choisie par le client (obligatoire pour générer une vidéo).';

create table if not exists public.avatar_video_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  status text not null default 'queued', -- queued | running | done | error | cancelled
  script text not null,
  target_key text not null,
  avatar_look_id text,
  voice_id text,
  heygen_video_id text,
  result jsonb, -- {video_url, thumbnail_url, duration, credits} — URLs seulement, jamais d'octets
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.avatar_video_jobs is
  'File des rendus vidéo avatar IA (HeyGen). target_key = clé opaque du bloc frontend (ex. reel:{lineKey}) pour rattacher la vidéo même pop-up fermée.';

create index if not exists avatar_video_jobs_user_created_idx
  on public.avatar_video_jobs (user_id, created_at desc);

alter table public.avatar_video_jobs enable row level security;

drop policy if exists "avatar_video_jobs_own_rows" on public.avatar_video_jobs;
create policy "avatar_video_jobs_own_rows" on public.avatar_video_jobs
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
