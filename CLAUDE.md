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

## Tests E2E (non-régression)
Suite **Playwright** dans `e2e/` (projet npm séparé, hors base directory Netlify/Render). Tourne contre le **site dev déployé**, en **lecture seule** (aucune génération → zéro coût Anthropic/Apify).
- **Lancer** : `cd e2e && npm install && npx playwright install chromium && npx playwright test`. Détails dans `e2e/README.md`.
- **Cible** surchargeable : `E2E_BASE_URL=https://lkd-outreach.netlify.app` pour viser la prod (défaut = dev).
- **Compte de test** : `qa.playwright@lkd-outreach.app` / `Lkd!Test2026` (dans Supabase `auth.users`+`auth.identities`, email confirmé).
- **Après toute feature UI** : ajouter/ajuster un spec dans `e2e/tests/` et relancer la suite avant de merger.
- **Pièges** : Playwright **pinné `1.49.1`** (1.61 cassé avec Node 22). Création SQL d'un user GoTrue → colonnes token à `''` (pas `NULL`), `auth.identities.email` est générée.
- **Génération réelle** (post/idée/analyse) : non couverte (coûteuse) — testée manuellement par Alex.

## Changelog

### 2026-06-19 (tests E2E de non-régression — Playwright)
- **Suite Playwright** dans `e2e/` (projet npm dédié, séparé du front) qui tourne contre le **site dev déployé** avec un compte Supabase de test. **Lecture seule** : aucun test ne déclenche de génération (zéro coût Anthropic/Apify) ni de publication.
- **Specs** : `smoke.spec.ts` (landing + ouverture du modal de connexion, sans auth), `authenticated.spec.ts` (onglets Mon profil, Mes contenus, Générateur, Assistant — rendu + absence d'erreur de chargement). `auth.setup.ts` logge une fois et persiste la session via `storageState`. Helpers `login()`/`gotoTab()`.
- **Compte de test** : `qa.playwright@lkd-outreach.app` / `Lkd!Test2026` (créé directement dans `auth.users`+`auth.identities` via MCP Supabase, email confirmé). ⚠️ Piège GoTrue : les colonnes token (`confirmation_token`, `recovery_token`, `email_change*`, `phone_change*`, `reauthentication_token`) doivent être `''` et non `NULL`, sinon login = `Database error querying schema`. `auth.identities.email` est une colonne générée (ne pas l'insérer).
- ⚠️ **Playwright 1.61.0 cassé** avec Node 22 (`context.conditions?.includes is not a function` à l'import d'un module TS local) → **pinné `1.49.1`**.
- **Lancer** : `cd e2e && npm install && npx playwright install chromium && npx playwright test`. Cible surchargeable par `E2E_BASE_URL` (prod : `https://lkd-outreach.netlify.app`).
- Pas d'impact build : `e2e/` est hors du base directory Netlify (`frontend/`) et de Render.

### 2026-06-19 (persistance : profil auto-sauvé + posts générés en base)
- **Profil éditorial auto-sauvé** : le bouton **« Pré-remplir »** (`draftProfile` dans `page.tsx`) enchaîne désormais un `PUT /me/profile` juste après la génération → le profil généré est **persisté immédiatement** en base, plus besoin de cliquer « Sauvegarder ». Cause du bug initial : `/me/profile/draft` ne fait que renvoyer le brouillon (remplit le formulaire), seul `PUT /me/profile` écrit en base.
- **Posts générés persistés** : nouvelle table `generated_posts` (migration `0006_generated_posts.sql`, RLS `auth.uid() = user_id`) + `save_generated_posts(token, topic, variants)` dans `db.py`. `/generate` auto-sauve les variants par utilisateur et renvoie `save_error`. Colonnes : `topic, editorial_role, hook_type, strategy, predicted_lift, post`.
- **Idées** : déjà auto-sauvées dans `generated_ideas` (via `save_ideas`, appelé par `/ideas`) — table existante créée manuellement, **formalisée** dans la migration 0006 en `if not exists`.
- **DB** : migration 0006 **déjà appliquée** sur Supabase (via MCP) — pas besoin de la rejouer. Base partagée prod+dev.
- ⚠️ **Déploiement** : mergé `dev → main` (Render backend + Netlify prod). Aucune nouvelle env var.

### 2026-06-19 (interface « Mes contenus » : relire & réutiliser posts/idées sauvegardés)
- **Nouvel onglet « Mes contenus »** (`view === "library"` → `LibraryView` dans `page.tsx`, premium/auth) : deux sous-onglets **Posts** / **Idées** listant tout ce qui a été généré et persisté. Chargé via `GET /me/generated-posts` + `GET /me/generated-ideas` au montage.
- **Réutilisation** : bouton « Générer ce post » (idée) / « Régénérer sur ce sujet » (post) → remonte le sujet à `Home` (`generatorSeed = {topic, nonce}`) qui bascule sur l'onglet Générateur ; `Generator` reçoit la prop `seed` et un `useEffect([seed.nonce])` pré-remplit le sujet et lance la génération. Aussi : copier le post / l'accroche (clipboard), supprimer (optimiste + `DELETE`).
- **Backend** : `list_generated_ideas`/`list_generated_posts` + `delete_generated_idea`/`delete_generated_post` dans `db.py` ; endpoints `GET`/`DELETE /me/generated-ideas[/{id}]` et `…/generated-posts[/{id}]` dans `api.py` (tous `require_token`, scope RLS `user_id`).
- Pas de nouvelle migration (réutilise `generated_posts`/`generated_ideas` de la 0006).

### 2026-06-18 (ALE-79 : assistant conversationnel V1 — chat avec mémoire + contexte)
- **Objectif** : remplacer les générations one-shot stateless (`/ideas`, `/generate`) par un **chat itératif** type Claude, avec mémoire, contexte client et benchmark influenceurs. **V1 sans outils** (le tool-use — image, publication, relance d'analyse depuis la conversation — est l'évolution prévue, pas encore implémentée).
- **DB** : migration `supabase/migrations/0005_chat.sql` → tables `chat_conversations` + `chat_messages` (RLS `auth.uid() = user_id`, message insert vérifie aussi la propriété de la conversation). **À exécuter manuellement dans le SQL editor Supabase.**
- **Backend** : `POST /chat` en **streaming SSE** (`event: meta|delta|done|error`) ; `GET /chat/conversations` + `GET /chat/conversations/{id}/messages`. Helpers `create/get/list_chat_conversations`, `get/append_chat_message` dans `db.py`. `chat_stream()` + `_chat_system_prompt()` dans `llm.py` (réutilise `_build_benchmark` + `get_user_ai_context`, garde les 24 derniers messages, tracke l'usage Anthropic).
- **Front** (`page.tsx` + `globals.css`) : onglet **« Assistant »** (premium/auth), liste de conversations à gauche, fil de messages markdown streamé (lecture du `ReadableStream` SSE), quick-actions, Cmd/Ctrl+Entrée pour envoyer.
- **Origine** : code repris de la PR #16 (branche `cursor/ALE-79-…`) mais **réappliqué proprement sur `dev`** (la PR ne mergeait pas : conflits `page.tsx` + un changement `analyses` déjà livré par ailleurs). Code chat uniquement.
- ⚠️ **Déploiement** : mergé `dev → main` (Render + Netlify prod). Exécuter la migration 0005 avant usage, sinon `/chat` renvoie une erreur (tables absentes). `ANTHROPIC_API_KEY` déjà sur Render.
- **Suite** : passage en tool-use (commencer par l'outil `generate_image` qui appelle `src/image_gen.py` ; ALE-68 image gen déjà codée, en phase de test).

### 2026-06-18 (ALE-80 : sécuriser la publication LinkedIn — modal de confirmation + brouillon)
- **Modal de confirmation** : clic sur « Publier sur LinkedIn » ouvre désormais une modal avec aperçu du texte et boutons Annuler / Confirmer. La publication réelle n'est déclenchée qu'au Confirmer.
- **Brouillon Zernio** : nouveau bouton « Enregistrer en brouillon » sur chaque variant → appelle `/me/linkedin/publish` avec `draft:true` → Zernio reçoit `isDraft:true` (pas de `publishNow`). Message de succès distinct : « Brouillon enregistré ✓ ».
- **Backend** : `create_post` dans `src/zernio.py` accepte `is_draft=False` ; si vrai → `{isDraft:true}`, sinon → `{publishNow:true}`. `LinkedInPublishRequest` dans `api.py` ajoute `draft: bool = False` ; l'endpoint le relaie et retourne `"draft"` dans la réponse.
- **Front** (`page.tsx`) : nouveaux états `confirmIndex` (variant en attente) et `drafted` (variant sauvé en brouillon). `publishVariant(i, text, draft)` sépare ouverture de modal (publish) vs appel direct (brouillon). `doPublish(i, text, draft)` effectue l'appel API réel.
- Pas de nouvelle migration DB. `ZERNIO_API_KEY` déjà sur Render.

### 2026-06-17 (publication LinkedIn via Zernio — MVP publier-maintenant)
- **Objectif** : publier un post généré directement sur LinkedIn depuis l'app. Choix de **Zernio** (API REST `https://zernio.com/api/v1`, Bearer `sk_…`, serveur MCP dispo) plutôt que l'API officielle LinkedIn (partner review trop lourd).
- **Modèle** : 1 clé API serveur unique (`ZERNIO_API_KEY`) ; **1 « profile » Zernio par utilisateur** (= par client, archi actuelle 1 login = 1 profil éditorial) ; 1 compte LinkedIn connecté via OAuth dont on mémorise l'`accountId`.
- **Flux** : (1) `POST /v1/profiles {name}` → `profile._id` (créé à la 1ʳᵉ connexion), (2) `GET /v1/connect/linkedin?profileId=…&redirect_url=…` → `authUrl` (Zernio gère l'OAuth, redirige ensuite vers l'app avec `?linkedin=connected`), (3) au retour `GET /v1/accounts?profileId=…` → `_id` du compte LinkedIn stocké, (4) `POST /v1/posts {content, platforms:[{platform:"linkedin", accountId}], publishNow:true}`.
- **Backend** : nouveau `src/zernio.py` (client stdlib urllib, pas de dépendance HTTP ajoutée) + endpoints `GET /me/linkedin/status`, `POST /me/linkedin/connect`, `POST /me/linkedin/refresh`, `POST /me/linkedin/publish` dans `api.py`. Helpers `set_zernio_profile_id`/`set_zernio_account` dans `db.py`.
- **DB** : migration `supabase/migrations/0004_zernio.sql` → colonnes `zernio_profile_id`/`zernio_account_id`/`zernio_connected_at` sur `user_editorial_profiles`. **À exécuter manuellement dans le SQL editor Supabase.**
- **Front** (`page.tsx`) : hook `useLinkedIn`, encart « Publication LinkedIn » (connecter/connecté) dans l'onglet Profil, bouton **« Publier sur LinkedIn »** sur chaque variant généré, gestion du retour OAuth (`?linkedin=connected`) dans `Home` → `refresh` + bascule sur l'onglet Profil.
- **Limites V1** : publier-maintenant uniquement (pas de planification, pas de média/image), 1 seul compte LinkedIn par utilisateur.
- ⚠️ **Déploiement** : backend Render depuis `main` → nécessite merge `dev→main` + ajouter `ZERNIO_API_KEY` dans les env vars Render. Exécuter la migration 0004 avant.
- **Suite prévue** : agent chatbot (V1 simple : `/chat` SSE + contexte client + historique persistant) ; à terme l'agent publiera via le MCP Zernio.

### 2026-06-13 (job queue serveur : backlog multi-profils persistant + onglet dédié)
- **Nouvel onglet « Backlog »** (`view === "backlog"` → `JobsView` dans `page.tsx`, premium/auth requise) : on colle plusieurs profils (un par ligne), ça crée une **série** traitée côté serveur, profil par profil, avec statut live par ligne (polling `/jobs` toutes les 3 s tant qu'une série tourne). L'état vit en base → survit au refresh, à la fermeture d'onglet et à la reconnexion.
- **Backend** : `src/jobs.py` traite chaque série dans un **thread de fond** (verrou global `_compute_lock` pour sérialiser `run_analysis` — usage global + rate limit Apify). Endpoints `POST /jobs`, `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/resume` (relance les items non terminés après un redémarrage). Helpers `create_job`/`get_job`/`list_jobs`/`update_job`/`update_job_item` dans `db.py`. Chaque item terminé appelle `save_analysis` → le rapport apparaît aussi dans « Analyses récentes ».
- **DB** : migration `supabase/migrations/0001_analysis_jobs.sql` → tables `analysis_jobs` + `analysis_job_items` (RLS `auth.uid() = user_id`). **À exécuter manuellement dans le SQL editor Supabase** (le MCP n'a pas les droits DDL, pas de service-role en local).
- **Onglet unique « Analyser »** (décision suivante, même jour) : l'ancien onglet « Analyser » synchrone (single-profil) a été fusionné dans le job queue, qui devient **le seul point d'entrée**, renommé « Analyser » (`view === "analyze"` → `JobsView`). Les séries vivent dans `Home` (pas dans `JobsView`) → polling global + **badge de progression dans la sidebar visible sur toutes les pages**. Ouvrir un rapport terminé = vue markdown (`loadedReport`).
- **Essai gratuit anonyme retiré** : l'essai gratuit reposait sur l'analyse **synchrone** `/analyze` (rend la main après 60-90 s) → peu fiable en prod (timeout HTTP Render probable), alors que la queue async marche. Décision : **auth requise dans tous les cas** (`!isAuthed` → `requireAuth`), on capture l'email avant toute analyse. Plus de chemin synchrone exposé : la queue est le seul point d'entrée. `analyze()`/`Dashboard`/`Kpis`/`TopPosts`/`Patterns`/`LoadingState`/`Landing` + helpers freemium anon sont désormais **code mort** (laissés en place, à nettoyer dans un commit dédié).
- ⚠️ **Déploiement** : le backend Render déploie depuis `main` (partagé prod/dev) → la feature nécessite un merge `dev → main` pour être active en ligne (touche aussi la prod). Ordre : (1) exécuter la migration SQL, (2) merger dev→main, (3) vérifier `/health`.
- **Limite connue** : le thread porte le JWT user (~1 h de validité) → une série très longue pourrait expirer en cours ; OK pour des séries de quelques profils.

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

### 2026-06-12 (abonnés de retour : fallback actor profil)
- **Cause racine des abonnés manquants** : `harvestapi/linkedin-profile-scraper` exige depuis ~06/2026 une approbation de permissions « full access » dans la console Apify → chaque `fetch_profile` échouait (erreur avalée, maintenant loggée).
- **Fix** : fallback automatique sur `apimaestro/linkedin-profile-detail` ($0.005/profil, aucune approbation requise, schéma `basic_info` avec follower_count/connection_count/is_creator/about/location) — c'est aussi le nouvel actor par défaut. Mapping ajouté dans `normalize_profile`. L'env `APIFY_PROFILE_ACTOR` (Render/local) peut rester sur harvestapi : le fallback prend le relais.

### 2026-06-12 (libellés grand public dans le rapport)
- **Jargon traduit** : hooks (`bold_claim` → « Affirmation tranchée »), stages (`TOFU` → « Attraction »), formats (`text` → « Texte seul ») via `HOOK_LABELS`/`STAGE_LABELS`/`FORMAT_LABELS` dans `report.py`. Le code technique reste visible en italique discret `_( … )_`, stylé petit/grisé via `.markdown table em` dans globals.css.
- **Sections renommées** : « Mix funnel TOFU/MOFU/BOFU » → « Répartition du contenu — attirer, éduquer, convertir » ; « Patterns (synthèse LLM) » → « Analyse stratégique » ; « CTA commentaires » → « Appels à commenter » ; colonnes Comments/Shares → Commentaires/Partages.
- **Table de hooks heuristique supprimée du rapport** (contradictoire avec la classification LLM, source de confusion).
- **Frontend** : onglet Patterns avec les mêmes libellés français (`hookLabel()`).
- **Prompt LLM** : la synthèse doit utiliser les libellés français en prose, jamais les codes.

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
