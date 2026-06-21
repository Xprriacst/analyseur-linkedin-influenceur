-- Migration 0015 : ajout du support de la plateforme Instagram
-- À exécuter manuellement dans le SQL editor Supabase.

-- Add platform to influencers (unique constraint change)
ALTER TABLE public.influencers ADD COLUMN IF NOT EXISTS platform text NOT NULL DEFAULT 'linkedin';

-- Drop old unique constraint (user_id, handle) and replace with (user_id, handle, platform)
DO $$ BEGIN
  ALTER TABLE public.influencers DROP CONSTRAINT IF EXISTS influencers_user_id_handle_key;
EXCEPTION WHEN others THEN NULL; END $$;
ALTER TABLE public.influencers ADD CONSTRAINT influencers_user_id_handle_platform_key UNIQUE (user_id, handle, platform);

-- Add platform to posts and analyses
ALTER TABLE public.posts ADD COLUMN IF NOT EXISTS platform text NOT NULL DEFAULT 'linkedin';
ALTER TABLE public.analyses ADD COLUMN IF NOT EXISTS platform text NOT NULL DEFAULT 'linkedin';

-- Instagram-specific post columns (null for LinkedIn posts)
ALTER TABLE public.posts ADD COLUMN IF NOT EXISTS views bigint;
ALTER TABLE public.posts ADD COLUMN IF NOT EXISTS video_duration_s numeric;
ALTER TABLE public.posts ADD COLUMN IF NOT EXISTS transcript text;
ALTER TABLE public.posts ADD COLUMN IF NOT EXISTS hashtags jsonb;
ALTER TABLE public.posts ADD COLUMN IF NOT EXISTS music jsonb;

-- Add platform column to analysis_jobs (so we know which pipeline ran)
ALTER TABLE public.analysis_jobs ADD COLUMN IF NOT EXISTS platform text NOT NULL DEFAULT 'linkedin';
