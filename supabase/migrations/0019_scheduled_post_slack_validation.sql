-- ALE-120 : validation Slack des posts LinkedIn programmés.
-- Les posts déjà programmés avant cette migration restent publiables pour ne pas
-- bloquer silencieusement une file existante.

ALTER TABLE public.scheduled_posts
  ADD COLUMN IF NOT EXISTS slack_status text;  -- null | pending | validated | declined

ALTER TABLE public.scheduled_posts
  ADD COLUMN IF NOT EXISTS slack_message_ts text;

UPDATE public.scheduled_posts
SET slack_status = 'validated'
WHERE status = 'pending'
  AND slack_status IS NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'scheduled_posts_slack_status_check'
  ) THEN
    ALTER TABLE public.scheduled_posts
      ADD CONSTRAINT scheduled_posts_slack_status_check
      CHECK (slack_status IS NULL OR slack_status IN ('pending', 'validated', 'declined'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_scheduled_posts_due_validated
  ON public.scheduled_posts (scheduled_at)
  WHERE status = 'pending' AND slack_status = 'validated';
