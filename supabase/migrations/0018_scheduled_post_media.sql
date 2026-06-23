-- ALE-119 : images sur les posts LinkedIn planifiés
-- Les images uploadées/générées sont conservées jusqu'au passage du cron.

ALTER TABLE public.scheduled_posts
    ADD COLUMN IF NOT EXISTS media_items jsonb NOT NULL DEFAULT '[]'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'scheduled_posts_media_items_is_array'
          AND conrelid = 'public.scheduled_posts'::regclass
    ) THEN
        ALTER TABLE public.scheduled_posts
            ADD CONSTRAINT scheduled_posts_media_items_is_array
            CHECK (jsonb_typeof(media_items) = 'array');
    END IF;
END $$;
