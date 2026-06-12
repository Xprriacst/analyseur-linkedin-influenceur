# Notes Claude — Architecture Analyseur LinkedIn

## Environnements déployés

| Env | Frontend (Netlify) | Backend (Render) | Branche git |
|---|---|---|---|
| **Prod** | `lkd-outreach.netlify.app` (ID `81f75c05`) | `analyseur-linkedin-influenceur-api.onrender.com` | `main` |
| **Dev** | `lkd-outreach-dev.netlify.app` (ID `35a2cf5e`) | idem (même service Render) | `dev` |

### Variables d'env Netlify (identiques sur les deux sites)
- `BACKEND_URL` → URL Render (server-side, proxy Next.js)
- `NEXT_PUBLIC_BACKEND_URL` → URL Render (client-side, appels directs)
- `NEXT_PUBLIC_SUPABASE_URL` → `https://zcxaxwqkswuefzlzpgvi.supabase.co`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY` → clé anon Supabase

### Règle de déploiement
- Tout push sur `main` → déploiement auto sur prod
- Tout push sur `dev` → déploiement auto sur dev (après liaison GitHub dans Netlify UI)
- Les URLs hardcodées ont été remplacées par ces vars dans `frontend/app/page.tsx`, `frontend/app/api/[...path]/route.ts` et `netlify.toml`

### Dev local
Copier `frontend/.env.local.example` → `frontend/.env.local` et pointer `BACKEND_URL` / `NEXT_PUBLIC_BACKEND_URL` sur `http://localhost:8000`.

### Règle changement de domaine (reminder)
Tout changement de domaine frontend = 3 actions atomiques : (1) CORS dans `api.py`, (2) Supabase Auth Site URL + Redirect URLs, (3) variables d'env Netlify. Ne pas marquer terminé sans avoir vérifié les 3.

## Changelog

### 2026-06-12 (fiabilité des analyses : dates, formats, corpus, croisements)
- **Bug dates** : `_parse_date` ne gérait pas les timestamps epoch ms → en prod (schéma harvestapi, `postedAt.timestamp` int matché en premier) toutes les dates étaient perdues ("25 posts sur 0 jours", cadence/timing vides). Fix : parse epoch s/ms (int et str), dates ISO prioritaires, fallback URN (`activity_id >> 22` = epoch ms), garde-fou années 2005..now+1 (élimine le "1781-07-12").
- **Bug formats** : `_detect_format` ignorait `media.type` (apimaestro) et `postImages`/`article`/`repost` (harvestapi) → tout sortait "100% text" alors qu'Ugo Sartini a 21 images + 3 vidéos sur 25 posts. Les recos LLM "lance des carrousels" étaient un artefact.
- **Bug corpus (cas Lorenzo)** : `compute_stats` réduisait le corpus aux seuls posts datés dès qu'une date parsait → stats d'engagement sur 1 post pendant que les patterns tournaient sur 50. Fix : l'engagement porte toujours sur tous les posts (moins les <24h datés) ; seules les métriques temporelles utilisent le sous-ensemble daté ; cadence seulement si ≥5 posts datés.
- **Likes sous-comptés ~10%** : `stats.total_reactions` prioritaire sur `stats.like` (qui excluait love/support/celebrate/insight).
- **Engagement organique** : nouveau `median_organic` (likes+reposts) + `organic_rate_pct` — les commentaires sont gonflés par les CTA "commente X pour recevoir" (Ugo : 3.4% brut vs 0.77% organique). Colonne CTA ✅ dans le top 5.
- **Croisements** : `engagement_by_classification()` → engagement médian par stage TOFU/MOFU/BOFU et par hook_type (colonnes dans les tables du rapport + payload LLM `stage_engagement`/`hook_engagement`/`cta_effect`).
- **Grounding LLM** : la synthèse reçoit url/likes/comments/has_cta par post + règles strictes (chiffres exacts uniquement, pas de conclusion format hors `format_mix_pct`).
- **Rapport** : section "Fréquence & timing" réaffichée uniquement si dates dispo (heures de Paris), top 5 par engagement total, labels distincts pour les 2 classifications de hooks, handle URL-décodé, "(dates indisponibles)" au lieu de "sur 0 jours".
- **Coûts Apify** : pricing harvestapi ajouté ($0.002/post, $0.004/profil) + fallback $0.002/item pour actor inconnu (fini le "~$0.0").
- **Reste à faire (proposé)** : détection de near-duplicates/recyclage de templates, scraper de commentaires Apify sur les top posts (qualité d'audience + leads).

### 2026-06-12 (version client : profil, liens, historique, URLs accentuées)
- **Nom du profil** : harvestapi renvoie `firstName`/`lastName`, jamais `fullName` → `normalize_profile` construisait un nom vide (titre du rapport = handle, historique illisible). Fix : name = fullName ou firstName+lastName.
- **Bloc "Profil en chiffres" toujours affiché** : avant, si le scrape profil échouait, tout le bloc (abonnés, connexions…) disparaissait silencieusement. Maintenant rendu avec "indisponible" pour les valeurs manquantes.
- **URLs accentuées/emoji** (ex. `clément-geynet-☀️-zénithia`) : `normalize_url` reconstruit l'URL avec handle percent-encodé (unquote→quote, pas de double encodage), query params iOS strippés. `extract_handle` renvoie la forme décodée (cache/db/affichage). ⚠️ Les caches existants au nom encodé (`th%C3%A9ophile…`) ne matchent plus → re-scrape au prochain run.
- **Échecs plus jamais mis en cache** : items d'erreur (`{"message", "profile_input"}`) filtrés, cache écrit seulement si résultats non vides.
- **Version client** : suppression de tout l'affichage technique — grille Apify/tokens/coût au-dessus du rapport, onglet "Usage", ligne "Coût estimé" du loading, section "Usage & coûts estimés" du markdown (les données restent en base dans `analyses.usage`).
- **Liens cliquables** : profil = `[handle](url)`, top 5 = extrait du post cliquable, plus de liste d'URLs brutes.
- **Historique ("Analyses récentes")** : affiche le prénom + nom de l'influenceur (jointure `influencers(name)`, fallback handle décodé) au lieu de `handle — date`.
- **remark-gfm ajouté au frontend** : les tableaux markdown du rapport se rendent enfin en vrais tableaux HTML (avant : texte brut avec des pipes) + styles `.markdown table` dans globals.css.
- **Rappel déploiement** : le backend Render (`analyseur-linkedin-influenceur-api`, partagé prod/dev) déploie depuis `main` uniquement → les changements backend nécessitent un merge dev→main. Netlify dev ne rebuild que si `frontend/` change (base directory).

### 2026-06-11 (config Supabase Auth manquante après renommage Netlify)
- **Bug** : après le renommage Netlify en `lkd-outreach.netlify.app`, la **Site URL** Supabase pointait encore vers `localhost` → les redirections OAuth et confirmations email échouaient → les analyses ne s'enregistraient pas en prod.
- **Fix** : dans le dashboard Supabase → Authentication → URL Configuration :
  - **Site URL** → `https://lkd-outreach.netlify.app`
  - **Redirect URLs** → ajouter `https://lkd-outreach.netlify.app/**`
- **Leçon** : tout changement de domaine frontend = 3 actions atomiques : (1) CORS backend `api.py`, (2) Supabase Auth Site URL + Redirect URLs, (3) variables d'env frontend si nécessaire. Ne pas marquer terminé sans avoir vérifié les 3.

### 2026-06-11 (fuite cross-user : vraie cause racine = state React)
- **Audit complet** : RLS Supabase correctes (`auth.uid() = user_id` sur les 4 tables, RLS activé), données bien séparées par `user_id` en base, backend Render à jour (`/reports`, `/dashboard`, `/dashboard/growth`, `/ideas` → 401 sans token, `/health` → `"supabase": true`). La piste « policies permissives » est écartée.
- **Vraie cause** : dans `frontend/app/page.tsx`, `Home` détient `reports`/`result`/`loadedReport` et rend `<AuthGate>` en dessous. Au logout, AuthGate démonte l'app-shell mais `Home` ne se démonte jamais → son state survit. `loadReports()` n'était appelé qu'au mount initial. Donc : A analyse → logout → B se connecte dans le même onglet → B voit les rapports/résultats de A restés en mémoire.
- **Fix** : listener `supabase.auth.onAuthStateChange` dans `Home` — purge du state par utilisateur (reports, result, loadedReport, error, view) dès que le `user.id` change, puis re-fetch de `/reports` avec le nouveau token (via `setTimeout` pour éviter le deadlock supabase-js dans le callback).

### 2026-06-11 (fuite cross-user corrigée)
- **Bug** : `/reports` servait les fichiers `reports/*.md` du disque sans auth → la sidebar « Analyses récentes » montrait les rapports de TOUS les utilisateurs.
- **Fix** : `/reports` lit désormais `analyses.report_markdown` depuis Supabase scopé par user (401 sans token quand Supabase est configuré ; fallback disque uniquement en dev). Frontend : header `Authorization` envoyé sur `/reports`.
- `/analyze` expose `save_error` quand la persistance Supabase échoue (au lieu d'un `except: pass` silencieux) + bandeau d'avertissement frontend.
- ⚠️ À vérifier en prod : `/health` doit montrer `"supabase": true` sur Render, sinon les endpoints retombent sur le cache disque éphémère.

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
Supabase project : `zcxaxwqkswuefzlzpgvi` ("Linkedin analyse", eu-west-1)

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
