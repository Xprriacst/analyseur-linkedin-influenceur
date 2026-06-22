-- ALE-104 : colonne slack_status sur generated_posts pour la validation Slack
-- Même structure que generated_ideas.slack_status (migration 0010).

ALTER TABLE public.generated_posts
  ADD COLUMN IF NOT EXISTS slack_status text;  -- null | pending | validated | declined
