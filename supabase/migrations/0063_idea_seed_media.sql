-- 0063 — Photos jointes aux idées du réservoir.
--
-- Joëlle (vue ideas_only) doit pouvoir joindre des photos quand elle ajoute une
-- idée de post — typiquement les photos d'un bien, en plus ou à la place d'un
-- lien d'annonce. Sans ça, le réservoir n'accepte que du texte : les photos ne
-- peuvent être ajoutées qu'après coup par l'agence, ou jamais.
--
-- Format = même `media_items` que generated_posts / scheduled_posts (items
-- Zernio `{type, url, title?}`). Grants au niveau table (0007) → la nouvelle
-- colonne est couverte automatiquement pour `authenticated`.
-- Idempotente.

alter table public.idea_seeds
  add column if not exists media_items jsonb not null default '[]'::jsonb;

comment on column public.idea_seeds.media_items is
  'Photos jointes à l''idée (URLs publiques Zernio). Embarquées à la génération / publication.';
