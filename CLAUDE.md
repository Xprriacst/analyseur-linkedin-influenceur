# Notes Claude — Architecture Analyseur LinkedIn

## Changelog

### 2026-06-10 (étape 1 implémentée)
- **Étape 1 livrée** : `/generate`, `/ideas`, `/dashboard`, `/dashboard/growth`, `/dashboard/ai-analysis` lisent désormais Supabase scopé par utilisateur (RLS) via `db.get_user_corpus()` + `_get_influencers()` dans `api.py`.
- Quand Supabase est configuré, ces endpoints exigent un token (401 sinon) ; sans Supabase (dev local), fallback sur le cache disque.
- `dashboard_growth` refactoré en `_compute_growth(influencers)` (fonction pure, réutilisée par l'analyse IA).
- Frontend : envoi du header `Authorization` sur les 5 appels (`authHeaders()`), le proxy Next `/api` forwardait déjà les headers.

### 2026-06-10
- **Audit DB Supabase** : vérification des tables existantes (`profiles`, `influencers`, `posts`, `analyses`) + extensions disponibles. `vector` (pgvector 0.8.0) disponible mais non installé.
- **Diagnostic backend** : identifié que Supabase est utilisé en write-only. Les endpoints `/generate`, `/ideas`, `/dashboard` et `/dashboard/ai-analysis` lisent le cache disque (`cache/`) au lieu de la base, ce qui rend la génération globale/éphémère et pas multi-utilisateur.
- **Architecture cible définie** en 3 étapes :
  1. Vrai backend par utilisateur (brancher lecture sur Supabase, scope `user_id`)
  2. Boucle de feedback (`user_posts` : posts générés → publiés → métriques réelles)
  3. RAG pgvector (uniquement quand le volume dépasse la capacité du prompt)
- **Création de ce fichier** pour centraliser les décisions et le contexte projet.

## Contexte
Projet : Analyseur-linkedin-influenceur
Supabase project : `zcxawwqkswuefzlzpgvi` ("Linkedin analyse", eu-west-1)

## DB actuelle (schema public)
- `profiles` → app profile lié à auth.users
- `influencers` → 3 rows, RLS on, raw_profile + raw_posts (jsonb)
- `posts` → 75 rows, RLS on, text + engagement metrics
- `analyses` → 3 rows, RLS on, report_markdown + stats/classifications/synthesis/cta_stats/usage (jsonb)
- Extension `vector` (pgvector 0.8.0) disponible mais **pas installée**

## Diagnostic actuel

### 1. Write-only Supabase
`POST /analyze` persiste bien les analyses (`db.save_analysis`) mais uniquement quand un `token` user est fourni. C'est du best-effort (RLS scopé par `user_id`).

### 2. Génération + Dashboard lisent le DISQUE, pas Supabase
- `/generate`, `/ideas`, `/dashboard`, `/dashboard/ai-analysis` appellent `_load_cached_influencers()` qui lit des fichiers JSON dans le dossier `cache/` du serveur.
- **Problèmes** :
  - Génération globale et partagée (pas par utilisateur)
  - Cache éphémère sur un serveur déployé (Render/Netlify)
  - Les données en base ne sont **jamais relues** pour générer

→ **Supabase est une archive morte aujourd'hui.**

## Architecture cible

### Étape 1 — Vrai backend par utilisateur (PRIORITAIRE)
Modifier les endpoints de génération et dashboard pour lire depuis Supabase (scope `user_id`) au lieu du cache disque.

**Actions concrètes :**
- Ajouter dans `src/db.py` : `get_user_influencers()`, `get_user_posts()`, `get_user_analyses()`
- Adapter `_build_benchmark()` et `generate_posts()` / `generate_ideas()` pour accepter une source de données injectable (cache disque OU base)
- Modifier `/generate`, `/ideas`, `/dashboard` pour récupérer le token user et passer les données Supabase

### Étape 2 — Boucle de feedback (post-génération)
- Nouvelle table `user_posts` : posts générés → publiés → métriques réelles (likes/comments)
- Comparaison prédit vs réel
- **Type de donnée : analytique chiffrée → SQL pur**, pas de vecteurs

### Étape 3 — RAG (pgvector) — uniquement quand justifié
Le RAG devient utile quand :
- Le corpus dépasse la capacité du prompt (centaines/milliers de posts)
- Besoin de recherche sémantique ("posts similaires à celui-ci", chat avec les analyses)

**Schéma envisagé :**

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE public.embeddings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id),
  source_type text NOT NULL,        -- 'post' | 'synthesis' | 'report'
  source_id uuid NOT NULL,          -- FK logique
  influencer_id uuid REFERENCES public.influencers(id),
  content text NOT NULL,            -- chunk de texte
  embedding vector(1536),           -- selon modèle d'embedding
  metadata jsonb,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX ON public.embeddings USING hnsw (embedding vector_cosine_ops);
```

### Règle d'or
| Type de donnée | Outil |
|---|---|
| Données chiffrées (stats, engagement, croissance) | SQL pur |
| Texte non structuré à retrouver par sens | RAG / pgvector |
| Tant que tout tient dans le prompt | Backend SQL suffit |

## Prochaine action
Étape 1 ✅ faite. Suite : étape 2 — boucle de feedback (table `user_posts` : posts générés → publiés → métriques réelles).
