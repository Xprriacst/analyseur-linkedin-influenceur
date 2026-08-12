-- 0063 — Mémoire posts structurée : fiche compacte au lieu du texte brut tronqué.
--
-- Jusqu'ici la mémoire des posts déjà créés (db.get_recent_post_memory,
-- llm._format_recent_posts) collait le début tronqué (300-400 caractères) de
-- chaque post récent dans le prompt. Ce lot ajoute une fiche structurée par
-- post — {subject, angle, products, hook} — calculée UNE FOIS à la CRÉATION du
-- post (sauvegarde ou programmation), et injectée à la place du texte brut
-- quand elle est disponible : moins de tokens, l'essentiel visible même si
-- l'info utile est en bas du post.
--
-- `memory_card` est jsonb et NULLABLE par construction : la fiche est calculée
-- par un appel IA annexe best-effort (src/llm.py::build_post_memory_card) — si
-- l'appel échoue (réseau, clé absente, JSON invalide), la colonne reste NULL et
-- la lecture de la mémoire retombe sur le texte brut tronqué (comportement
-- historique). Les lignes déjà existantes en base restent à NULL : elles
-- continuent de fonctionner exactement comme avant ce lot (rétrocompatible par
-- construction, aucun backfill nécessaire).
--
-- Idempotent (convention du repo) : rejouable sans effet de bord.

alter table if exists public.generated_posts
  add column if not exists memory_card jsonb;

alter table if exists public.scheduled_posts
  add column if not exists memory_card jsonb;

comment on column public.generated_posts.memory_card is
  'Fiche mémoire compacte {subject, angle, products, hook} calculée une fois à la création du post. NULL = repli sur le texte brut tronqué (posts antérieurs à ce lot, ou échec best-effort de l''extraction).';
comment on column public.scheduled_posts.memory_card is
  'Fiche mémoire compacte {subject, angle, products, hook} calculée une fois à la création du post. NULL = repli sur le texte brut tronqué (posts antérieurs à ce lot, ou échec best-effort de l''extraction).';
