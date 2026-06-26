-- Migration 0022 : étendre generated_ideas pour les idées « une ligne »
-- (ALE-143) — colonnes nullable, idempotente.
ALTER TABLE public.generated_ideas
  ADD COLUMN IF NOT EXISTS line text,
  ADD COLUMN IF NOT EXISTS source_type text,
  ADD COLUMN IF NOT EXISTS source_ref text,
  ADD COLUMN IF NOT EXISTS source_url text;
