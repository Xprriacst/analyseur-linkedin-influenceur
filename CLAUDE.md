# Notes Claude — Architecture Analyseur LinkedIn

## Environnements déployés

| Env | Frontend (Netlify) | Backend (Render) | Branche git |
|---|---|---|---|
| **Prod** | `lkd-outreach.netlify.app` (ID `81f75c05`) | `analyseur-linkedin-influenceur-api.onrender.com` | `main` |
| **Dev** | `lkd-outreach-dev.netlify.app` (ID `35a2cf5e`) | `analyseur-linkedin-influenceur-api-dev.onrender.com` | `dev` |

### Variables d'env Netlify
- `BACKEND_URL` → URL Render de l'environnement (server-side, proxy Next.js)
- `NEXT_PUBLIC_BACKEND_URL` → URL Render de l'environnement (client-side, appels directs)
- `NEXT_PUBLIC_SUPABASE_URL` → `https://zcxaxwqkswuefzlzpgvi.supabase.co`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY` → clé anon Supabase

Valeurs backend attendues :
- Prod : `BACKEND_URL` / `NEXT_PUBLIC_BACKEND_URL` → `https://analyseur-linkedin-influenceur-api.onrender.com`
- Dev : `BACKEND_URL` / `NEXT_PUBLIC_BACKEND_URL` → `https://analyseur-linkedin-influenceur-api-dev.onrender.com`

### Variables d'env Render
- Service prod : branche `main`, start command `uvicorn api:app --host 0.0.0.0 --port $PORT`
- Service dev : branche `dev`, même start command, mêmes secrets que la prod (`ANTHROPIC_API_KEY`, `APIFY_*`, `ZERNIO_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, etc.)
- `CORS_ORIGINS` optionnel : liste d'origines supplémentaires séparées par des virgules si le slug Render dev change.
- Caveat : prod et dev partagent encore le même projet Supabase ; les tests dev peuvent donc écrire dans la même base.

### Règle de déploiement
- Tout push sur `main` → déploiement auto sur prod
- Tout push sur `dev` → déploiement auto sur Netlify dev + Render dev
- Les URLs hardcodées ont été remplacées par ces vars dans `frontend/app/page.tsx`, `frontend/app/api/[...path]/route.ts` et `netlify.toml`

### Dev local
Copier `frontend/.env.local.example` → `frontend/.env.local` et pointer `BACKEND_URL` / `NEXT_PUBLIC_BACKEND_URL` sur `http://localhost:8000`.

### Règle changement de domaine (reminder)
Tout changement de domaine frontend = 3 actions atomiques : (1) CORS dans `api.py`, (2) Supabase Auth Site URL + Redirect URLs, (3) variables d'env Netlify. Ne pas marquer terminé sans avoir vérifié les 3.

## Règles PR & agents (anti méga-PR)

> Contexte : des agents ont produit des méga-PR multi-issues, basées sur `main`, avec base périmée et marqueurs de conflit (PR #40/#41/#42 fermées sans merge ; #37/#39 ont dû être re-portées). Ces règles évitent que ça se reproduise. Elles sont **vérifiées en CI** (`.github/workflows/pr-guardrails.yml`) et par la **branch protection** sur `main`.

### Règles dures (non négociables)
1. **1 issue = 1 branche = 1 PR.** Jamais plusieurs issues dans une même PR. Si une issue en embarque d'autres, découpe.
2. **Brancher depuis `origin/dev` à jour** (`git fetch origin && git checkout -B <branche> origin/dev`). Jamais depuis `main`, jamais depuis une vieille base locale.
3. **Base de la PR = `dev`. Jamais `main`.** Seule exception : la PR de release `dev → main` (faite en fin de cycle, après test sur dev).
4. **Avant d'ouvrir la PR**, en local : `python -m py_compile api.py src/*.py` **vert**, `cd frontend && npm run build` **vert**, et **zéro marqueur de conflit** (`git grep -nE '^(<<<<<<< |>>>>>>> |=======$)'` ne renvoie rien).
5. **Migrations Supabase** : numéro = **prochain libre** dans `supabase/migrations/` au moment du merge (le repo est à 0013 le 2026-06-22 ; 0014 = analyse Instagram, 0015/0016 = ALE-104/109). Vérifier qu'aucune autre PR ouverte n'utilise le même numéro pour éviter une collision au merge. Migrations idempotentes (`IF NOT EXISTS`).
6. **Vérifier qu'aucune PR/branche n'existe déjà** pour l'issue avant d'en créer une (`gh pr list`, `git branch -a`).
7. **Périmètre** : ne traiter que les issues `Backlog`/`Todo`. Ignorer `Done`/`In Review`/`Cancelled`/`Duplicate` et les labels « manque d'info » / « à arbitrer ».
8. **Mettre l'issue Linear à jour** (statut `In Review` + lien de la PR) une fois la PR ouverte.

### Prompt agent corrigé (à donner aux agents qui ouvrent des PR)
> Tu traites **une seule** issue. (1) `git fetch origin` puis branche depuis **`origin/dev` à jour** ; (2) **base de la PR = `dev`, jamais `main`** ; (3) vérifie qu'aucune PR/branche n'existe déjà pour cette issue ; (4) ne prends que les issues en **Backlog/Todo** (ignore Done/In Review/Cancelled/Duplicate + labels « manque d'info » / « à arbitrer ») ; (5) migrations Supabase numérotées au **prochain numéro libre**, idempotentes ; (6) avant d'ouvrir : `py_compile` + `npm run build` **verts** et **zéro marqueur de conflit** ; (7) une PR ne couvre **qu'une issue** ; (8) mets l'issue à jour (In Review + lien PR).

### CI & protection
- **`.github/workflows/pr-guardrails.yml`** (sur chaque PR) : échoue si marqueurs de conflit présents, ou si la base est `main` sans venir de `dev`.
- **Branch protection `main`** : PR obligatoire + check `guardrails` requis + pas de push direct. `main` ne se met à jour que par release `dev → main`.

## Tests E2E (non-régression)
Suite **Playwright** dans `e2e/` (projet npm séparé, hors base directory Netlify/Render). Tourne contre le **site dev déployé**, en **lecture seule** (aucune génération → zéro coût Anthropic/Apify).
- **Lancer** : `cd e2e && npm install && npx playwright install chromium && npx playwright test`. Détails dans `e2e/README.md`.
- **Cible** surchargeable : `E2E_BASE_URL=https://lkd-outreach.netlify.app` pour viser la prod (défaut = dev).
- **Compte de test** : `qa.playwright@lkd-outreach.app` / `Lkd!Test2026` (dans Supabase `auth.users`+`auth.identities`, email confirmé).
- **Après toute feature UI** : ajouter/ajuster un spec dans `e2e/tests/` et relancer la suite avant de merger.
- **Pièges** : Playwright **pinné `1.49.1`** (1.61 cassé avec Node 22). Création SQL d'un user GoTrue → colonnes token à `''` (pas `NULL`), `auth.identities.email` est générée.
- **Génération réelle** (post/idée/analyse) : non couverte (coûteuse) — testée manuellement par Alex via la checklist `e2e/MANUAL-CHECKLIST.md` (génération, publication LinkedIn/image, persistance après refresh, isolation cross-user).

## Journal des routines agent
Les routines autonomes tiennent un **journal de bord versionné** : `docs/agent-journal.md` (sur `dev`, entrée la plus récente en haut). Chaque run y consigne : issues traitées + PR + statuts, difficultés rencontrées (erreurs exactes), leçons et états en suspens. **Tout agent qui démarre une routine doit lire les dernières entrées d'abord** ; tout run doit en ajouter une à la fin (seul cas de push direct autorisé sur `dev` : ce fichier de docs uniquement). Prompt de routine de référence : `docs/routine-agent-issues.prompt.md`.

## Changelog

### 2026-07-07 (release prod : Agent IG / Inbox Instagram + fix analyses Sonnet 5 — PR #197)
- **Report `dev → main`** de tout le travail livré sur `dev` depuis la release #175 (48 commits). PR **#197**, check `guardrails` vert, mergée le 2026-07-07 ~08:10 Paris → Render prod live (`dep-d969gs647okc73a2shrg`, terminé 06:12 UTC) + Netlify prod. `/health` prod OK (`sonnet-5`, supabase, service_role).
- **Contenu principal** : (1) **fix critique analyses** Sonnet 5 (désactivation réflexion adaptative sur appels JSON, PR #184 — la prod était cassée sur toutes les analyses) ; (2) **Agent IG / Inbox Instagram** complet (epic ALE-195/201→205 : modèle de données + transport ManyChat, cerveau Claude ancré FAQ, transcription des vocaux avec garde-fou SSRF, inbox in-app supervisée, garde-fou autopilot conditionnel, connexion ManyChat **multi-client**, UX plein écran + simulateur + FAQ éditable, guide de config du flow ManyChat nouvelle UI) ; (3) **Agent IA** : édition manuelle d'un post avant publication + pop-up image IA « ne quitte pas la page » ; (4) divers (polling inbox non-chevauchant, renommage « Inbox », fixes fils périmés/suggestions, journal de routines).
- **DB — 2 bases désormais séparées** (correction d'une note antérieure « base partagée ») : **prod** = `zcxaxwqkswuefzlzpgvi` (eu-west-1), **dev** = `aiaohrlmsqhdadgaqavx` (« Linkedin analyse DEV », eu-west-3, créée 2026-07-06, ALE-206). Migrations IG **appliquées sur la prod** au moment de la release (via MCP) : `0032_ig_prospect_agent` (tables `ig_conversations`/`ig_messages`/`ig_drafts` + RLS), `0033_ig_autopilot` (table `ig_decisions` + colonne `user_editorial_profiles.ig_autopilot_kill_switch`), `0035_ig_manychat_multi_client` (colonnes `user_integrations.webhook_token`/`webhook_secret` + index unique). `0034_ig_faq` (`ig_faqs`) était déjà présente. La base **dev** avait déjà tout le schéma IG. Vérifié : 5 tables IG + 2 colonnes ManyChat + kill-switch présents en prod.
- **Env vars prod** : `OPENAI_API_KEY` **déjà présent** (réutilisé de la génération d'image « GPT Image 2 » qui tourne en prod → sert aussi à la transcription des vocaux). Le reste de l'Agent IG est soit **configuré par client dans l'app** (clé API + secret ManyChat par utilisateur, modèle multi-client), soit a des **valeurs par défaut** (`MANYCHAT_*`, `IG_AUTOPILOT_CONFIDENCE_THRESHOLD=0.85`, `OPENAI_TRANSCRIBE_MODEL=whisper-1`). `IG_AUDIO_ALLOWED_HOSTS` optionnel (vide = tout hôte https public autorisé ; le renseigner = durcissement SSRF facultatif). **Aucune env var bloquante à ajouter.**
- **Repointage dev** : le service **dev** (Render/Netlify) pointe déjà sur la base dev `aiaohrlmsqhdadgaqavx` (repointage constaté effectif le 2026-07-06, ALE-206) — les tests dev n'écrivent donc plus dans la base prod. Reste à finir 206 : Auth du projet dev, user de test E2E, bandeau UI « base partagée » périmé à retirer.

### 2026-07-06 (fix : analyses en échec « Unterminated string » — réflexion adaptative Sonnet 5)
- **Bug (test Alex, 3 séries d'analyse consécutives en échec sur prod)** : chaque item échouait avec `Unterminated string starting at: line N column 5 (char ~2500-4300)`. Le scraping Apify réussissait ; c'est l'étape IA (classification/synthèse) qui cassait.
- **Cause** : depuis la bascule `ANTHROPIC_MODEL=claude-sonnet-5` (2026-07-04), la **réflexion adaptative** est active par défaut quand `thinking` est omis, et **ses tokens sont décomptés de `max_tokens`**. Sur les appels à réponse JSON (classify_posts 8192, synthesize 4096…), la réflexion mangeait le budget → JSON coupé en plein milieu → `json.loads` échoue. Exactement le risque documenté le 04/07 (« si troncature → thinking disabled »).
- **Fix (`src/llm.py`)** : helper `thinking_kwargs(model)` → envoie `thinking: {"type": "disabled"}` sur les modèles à réflexion adaptative par défaut (tag `sonnet-5`) pour **tous les appels structurés** (`_call`, `_call_streaming`, analyse stratégique dashboard). Le **chat de l'Assistant (`chat_stream`) garde la réflexion adaptative** (choix qualité du 04/07, inchangé). Ajout d'un garde-fou `stop_reason == "max_tokens"` → erreur claire « Réponse IA tronquée » au lieu du cryptique « Unterminated string ».
- **Aussi corrigés (même cause, échec silencieux)** : `src/instagram_hooks.py` (hooks IG, `max_tokens=1024`, retombait sur le pool statique) et `src/image_gen.py` (prompt d'illustration, `max_tokens=120`) — thinking désactivé + lecture des blocs `text` uniquement (au lieu de `content[0]` qui peut être un bloc de réflexion).
- Backend-only, aucune migration, aucune env var. À release `dev → main` rapidement : **la prod est cassée pour toutes les analyses** tant que ce fix n'est pas déployé.

### 2026-07-06 (autonomisation des routines agent : CI de build + hook SessionStart + prompt corrigé)
- **Diagnostic** : la routine autonome « traiter les issues Linear » ne créait jamais de PR ni ne lançait les tests. Causes vérifiées : (1) le prompt reposait sur le CLI **`gh`, absent des sessions Claude Code distantes** (GitHub s'y pilote via les outils MCP `create_pull_request`/`merge_pull_request`/…) ; (2) sessions fraîches sans `node_modules` → `npm run build` impossible ; (3) allowlist quasi vide → blocages permission en headless ; (4) Linear parfois non authentifié en session automatique.
- **CI renforcée** (`.github/workflows/pr-guardrails.yml`) : le job `guardrails` (déjà check requis par la branch protection) exécute désormais **`py_compile` (api.py + src/) + `npm ci` + `npm run build`** sur chaque PR. Le « vert » ne dépend plus de la bonne foi de l'agent → le merge auto dans `dev` devient sûr ; `main` reste protégé comme avant (PR vers main refusées sauf release dev→main, faite manuellement par Alex).
- **Hook SessionStart** (`.claude/hooks/session-start.sh`, enregistré dans `.claude/settings.json`) : `npm install` dans `frontend/` au démarrage des sessions distantes (`CLAUDE_CODE_REMOTE` only, idempotent, synchrone). Validé : hook OK (416 packages/17 s), `py_compile` OK, `npm run build` OK sans secret. **Actif pour toutes les sessions une fois mergé dans la branche par défaut.**
- **Allowlist** (`.claude/settings.json`) : `git fetch/checkout/push/…`, `npm ci/install/run build`, `python(3) -m py_compile` pré-autorisés pour les sessions headless.
- **Prompt de routine corrigé** : `docs/routine-agent-issues.prompt.md` — MCP GitHub au lieu de `gh`, branche depuis `origin/dev`, portes de contrôle locales + CI, gating cosmétique (auto-merge dev) vs comportement/données (In Review pour Alex), Linear best-effort, **règle anti-silence** (tout échec est rapporté avec l'erreur exacte). À coller dans la config de la routine.
- **Journal de bord des routines** : `docs/agent-journal.md` — chaque run lit les dernières entrées au début (mémoire inter-runs) et en ajoute une à la fin (fait/difficultés/leçons, poussée directement sur `dev`, docs uniquement). Voir section « Journal des routines agent » ci-dessus.

### 2026-07-04 (passage du modèle IA à Sonnet 5 — prod + dev)
- **Objectif (demande Alex)** : passer le modèle IA de **Sonnet 4.6 → Sonnet 5** (`claude-sonnet-5`), piloté par la var d'env `ANTHROPIC_MODEL` sur Render.
- **Correctif code requis** : Sonnet 5 rejette tout paramètre d'échantillonnage non-défaut (`temperature`/`top_p`/`top_k`) avec une **erreur 400**, comme Opus 4.7/4.8. Ajout de `sonnet-5` aux `_NO_SAMPLING_TAGS` dans `src/llm.py` (`_accepts_temperature`) → on n'envoie plus `temperature` à ce modèle. Sonnet 4.6 continue de le recevoir (aucune régression). **PR #172** (dev) → **release #173** (`dev → main`). ⚠️ **Piège de séquençage** : le correctif doit être **live avant** de basculer `ANTHROPIC_MODEL`, sinon 400 sur chaque génération — respecté (le flip de l'env var redéploie depuis le commit qui contient déjà le correctif).
- **Env var basculée sur** : web **prod** (`srv-d8gn0n7lk1mc73f2pcf0`), web **dev** (`srv-d8u1cn5ckfvc73bad8sg`), cron **`analyseur-daily-ideas`** (`crn-d8qgda6q1p3s739phg9g`) et cron **`analyseur-weekly-posts`** (`crn-d9323gegvqtc739rcq8g`). Le cron `analyseur-linkedin-scheduler` (publication seule, pas de LLM) n'est **pas** touché. `/health` prod + dev confirment `"model":"claude-sonnet-5"`.
- **Choix assumé — réflexion adaptative** : sur Sonnet 5, omettre `thinking` **active la réflexion adaptative par défaut** (elle était OFF sur 4.6). Laissée activée (meilleure qualité de contenu). Effet visible : légère **pause avant réponse dans l'Assistant IA** (streaming). Si gênant ou si troncature sur petits `max_tokens` (hooks 2048, posts 3000) → option `thinking: {type: "disabled"}`.
- **Fable 5 écarté** : ~3× le prix d'Opus 4.8, réflexion toujours active, contraintes API (refus/rétention 30 j) ; surdimensionné pour de la génération de posts. Plafond utile = Opus 4.8.
- **Coûts** : Sonnet 5 = tarif d'intro $2/$10 par million de tokens jusqu'au 31/08/2026 (puis $3/$15) ; nouveau tokenizer ≈ +30 % de tokens vs 4.6. La **table de tarifs `src/usage.py` est périmée** (Opus 15/75 = ancien tarif ; Haiku 0.25/1.25 = 3.5) → à recaler.
- **Suite = ALE-193** (Backlog) : choisir le **modèle par usage** (Haiku 4.5 sur classification + prompt d'image ; Sonnet 5 / Opus 4.8 en option sur la génération) via surcharges d'env avec repli, + recalage des tarifs `usage.py`.

### 2026-07-04 soir (fix dev : boutons Slack cassés quand un Slack est relié à plusieurs comptes app)
- **Bug (test Alex)** : « ✏️ Modifier » dans le message Slack d'un post programmé → la pop-up s'ouvre **sans le texte**. Vérifié en base : le Slack d'Alex (`U0B9909K0QM`) est relié à **2 comptes app** (alexandre.errasti@gmail.com + alexandre@clareo-solutions.fr) et le post testé appartient au 2ᵉ.
- **Cause** : `db.get_user_by_slack_id` faisait `limit(1)` **sans ordre** → le webhook `/slack/webhooks/interactive` prenait un compte arbitraire, cherchait l'item chez le mauvais user, et retombait sur `{"id": item_id}` (modal vide). Même défaut **silencieux sur tous les boutons Slack** (Valider/Refuser idée, post direct, post programmé, soumission des modals d'édition) : l'action ne s'appliquait jamais aux items de l'autre compte.
- **Fix (PR #170)** : `db.get_users_by_slack_id` (tous les comptes reliés) + résolveur `_find_slack_owner` dans le webhook — chaque action teste les comptes reliés et agit sur celui qui **possède** l'item. Supprimé le fallback `{"id": item_id}` (pouvait publier un texte vide). Backend-only, aucune migration, aucune env var. Gardé volontairement même après qu'Alex a supprimé son doublon (reconnexion Slack) : filet de sécurité, comportement identique avec un seul compte relié. À savoir : l'app Slack pointe son interactivity URL sur le backend **prod** uniquement (vérifié dans les logs Render).
- **Release prod (PR #171, 2026-07-04 ~12:30 Paris)** : les 3 changements du jour (PR #169 image Slack, PR #170 multi-comptes, PR #168/ALE-192 prompt d'illustration) mergés `dev → main` → Render prod live (`dep-d94e0hd7vvec7389gra0`), `/health` OK. Reste à faire côté Alex : **re-valider dans Slack le post programmé du 05/07 09:00** (sa validation du matin était tombée dans le vide à cause du bug multi-comptes).

### 2026-07-04 soir (fix dev : image absente du message Slack d'un post programmé)
- **Bug (test Alex)** : programmer un post avec image + « Valider via Slack » → le message Slack partait **sans l'image** (upload comme image IA). La publication à l'échéance, elle, joignait bien l'image — seul l'aperçu Slack manquait.
- **Cause** : `/me/linkedin/schedule` stockait les images au **format brut** du front (`data_url` base64 ou `url` sans `type`) dans `scheduled_posts.media_items`, alors que `slack._image_blocks` n'affiche que des items normalisés `{type: "image", url: https…}`.
- **Fix (PR #169, mergée sur `dev`)** : les images sont mises en ligne **dès la programmation** via `zernio.prepare_image_media_items` (même mécanisme que « Publier maintenant ») → visibles dans le message de validation Slack et le message mis à jour après validation/refus ; le cron republie ces URLs telles quelles (idempotent) ; plus de base64 stocké en base. Backend-only, aucune migration, aucune env var. **En prod** via la release PR #171 (même jour). Les posts déjà programmés avant le fix gardent l'ancien format (publiés correctement, mais toujours sans image dans Slack).

### 2026-07-04 après-midi (release prod 2ᵉ vague : rework partout + UX pop-up image — ALE-189/190/191)
- **ALE-189** (PR #163) : « Retravailler avec l'Agent IA » disponible aussi dans le menu « ⋯ » du **post du jour** (Idée du jour) et des **posts sauvegardés** (Mes contenus) — le mécanisme `onRework` (ouvre l'Assistant avec le post en contexte) existait mais n'était branché que sur le Générateur.
- **ALE-190** (PR #164 + #165) : pop-up d'image IA **réductible en pastille** pendant la génération (elle continue, l'image se joint automatiquement), **alerte native du navigateur** si on ferme/recharge la page en pleine génération, et **preview de l'image** dans la pop-up à la fin (revient même si réduite). Durée affichée corrigée : « 2 à 3 min » (~2 min 30 mesurés dans les logs Render ; l'ancien « ~1 min » faisait croire à un échec). ⚠️ **Limite connue** : changer d'onglet **dans l'app** pendant la génération perd le résultat (le composant démonte) — la vraie file d'attente serveur = ALE-141.
- **ALE-191** (PR #166) : retouches libellés d'Alex embarquées — sous-titre « Générée avec GPT Image 2 » dans la pop-up image ; réservoir d'idées reformulé sans la mention « lien d'annonce ».
- **Debug utile (cas « je ne vois pas l'image »)** : vérifier les logs Render (`/generate-image` → 200 avec ~1,3 Mo = image OK) puis la base (`generated_posts.media_items`). Le cas d'Alex : image générée + jointe + persistée (URL `media.zernio.com`), il avait juste regardé avant la fin des 2 min 30.

### 2026-07-04 (release prod : barre d'actions unifiée + image IA + images Agent IA — ALE-185/68/188)
- **ALE-185 — barre d'actions unifiée** (PR #158) : les rangées de 6-8 boutons des cartes de post sont remplacées par un composant partagé `frontend/app/components/PostActionsBar.tsx` — bouton « Publier ▴ » (menu vers le haut : Publier maintenant / Programmer / Slack pour validation / Publier sur X, selon réseaux connectés) + bouton « ⋯ » (sauvegarder, joindre des images, image IA, régénérer, retravailler avec l'Agent IA, supprimer, selon la section). Utilisé par les **4 écrans** : Générateur, Mes contenus, Idée du jour, Agent IA (ce dernier garde « Copier » visible — pas de zone de texte avec icône en coin dans le chat). Alignement garanti par construction ; toute nouvelle action s'ajoute partout d'un coup.
- **ALE-68 — génération d'image IA réactivée** (PR #159 + #161, travail finalisé par une session parallèle, embarqué après revue) : pop-up en 2 temps — le **prompt d'illustration en français** est préparé (`/generate-image/prompt`, gratuit) et ajustable, l'image n'est générée (5 crédits, `generate_post_image(prompt=…)`) qu'à la validation. Remplace « Image IA — bientôt » (grisé ALE-150) sur les 4 écrans ; l'image générée rejoint les images jointes du post.
- **ALE-188 — joindre des images dans l'Agent IA** (PR #160) : « Joindre des images » dans le menu « ⋯ » sous chaque réponse (multi-upload 8 Mo, mêmes règles que le Générateur). Uploads + image IA fusionnés dans une même liste (miniatures télécharger/retirer) envoyée **partout** : publication LinkedIn, programmation, Slack, sauvegarde Mes contenus. Frontend-only.
- **E2E** : nouveau spec `e2e/tests/post-actions-menu.spec.ts` (lecture seule) — menus sur carte mockée (Mes contenus), conversation mockée (Agent IA) avec **upload réel d'un PNG factice**, entrée image IA active sans clic. Vert contre dev **et** prod déployés.
- ⚠️ **Constat hors périmètre** : 3 specs e2e préexistants échouent depuis une livraison antérieure (l'onglet « Mon profil » a maintenant un sous-onglet « Tableau de bord » par défaut que `authenticated.spec.ts` ne connaît pas) — à remettre d'aplomb dans un ticket dédié.
- **Déploiement** : release **PR #162 `dev → main`** mergée le 2026-07-04 (~11:15 Paris) → Netlify prod + Render prod. Aucune migration, aucune env var. Vérifié post-deploy : spec menus vert contre prod, `/health` OK.

### 2026-06-25 (Slack : post programmé affiché en entier + rappel délai cron — suivi ALE-120)
- **Bug** : le message de validation Slack d'un **post programmé** (`src/slack.py`, `send_scheduled_post_for_validation` / `update_scheduled_post_message`) tronquait le post à **300 caractères** (`text[:300] + "…"`) — un « aperçu ». Alex recevait le post coupé sur Slack.
- **Fix** : nouveau helper `_quote_full_text()` qui rend le post **complet** en blockquote mrkdwn multi-lignes (chaque ligne préfixée `> `), plafonné à **2900 caractères** (limite d'un bloc section Slack = 3000 ; post LinkedIn ≤ 3000). Le post est mis dans son **propre bloc** Slack (header + date séparés) pour ne pas grignoter le budget de 3000. Idem pour le message mis à jour après validation/refus (badge dans un bloc dédié). Backend-only, aucune migration, aucune env var.
- ⚠️ **Déploiement** : commit sur `dev` (`ce20644`) puis **PR #85 release `dev → main` mergée** (`e3bb588`) le 2026-06-25 → redeploy Render prod **live** (~17:00 Paris). Netlify a sauté le build (aucun changement dans `frontend/`, normal).
- **Test prod validé par Alex** : post programmé → reçu **complet** sur Slack → validé via boutons → **publié sur LinkedIn**. ✅
- **Rappel important (pas un bug) — délai de publication** : le cron `analyseur-linkedin-scheduler` tourne **toutes les 5 min** (`*/5 * * * *`). Un post n'est donc **pas publié à la seconde près** : il part au **tick suivant** après que (a) `scheduled_at <= now()` ET (b) `slack_status = 'validated'`. Délai observé jusqu'à ~3-5 min. Si Alex « ne voit pas le post », d'abord vérifier ce délai avant de suspecter un bug. Pour diagnostiquer : un post publié a `status='published'` + un `zernio_post_id` non nul dans `scheduled_posts`.

### 2026-06-25 (OOM Render résolu + grise analyse IA + ALE-109 rouverte / ALE-141 créée)
- **Incident debuggé (compte `tom@clareo-solutions.fr`)** : analyse LinkedIn de `lorenzo-coullet` figée puis erreur « Analyse interrompue (délai dépassé) ». **Le scraping n'était PAS en cause** : les 2 runs Apify ont réussi (posts `linkedin-profile-posts` SUCCEEDED ; profil `harvestapi/linkedin-profile-scraper` SUCCEEDED en 16s avec followerCount). Le blocage était **après les scrapes**, dans le traitement Python.
- **Cause racine = OOM kill du backend Render.** Le web service prod (`srv-d8gn0n7lk1mc73f2pcf0`) était en instance **Starter (512 MiB)**. Métriques mémoire = sawtooth : montée à ~510-527 MB (95-98 % du plafond) puis chute brutale + `instance_count=0` (OOM kill + restart) **en boucle** pendant l'incident. Le thread d'analyse meurt avant la fin → item reste `running` → `reconcile_stale_jobs` (`db.py`, `JOB_STALE_MINUTES=15`) le solde 15 min plus tard avec le message générique « délai dépassé » (le timeout interne 600s de `jobs.py` ne tire pas : le thread n'existe déjà plus). Exactement le risque prédit et reporté le 21/06.
- **Fix appliqué** : instance prod passée **Starter → Standard (2 GiB)** le 2026-06-25 (via dashboard Render — non modifiable par l'API/MCP). ⚠️ **Piège Render** : le **plan du compte** (« Pro », ~25 $) ≠ le **type d'instance par service**. Payer Pro ne change PAS la RAM ; il faut upgrader l'instance du service. Garder le compte en Pro (sinon retour spin-down = threads tués).
- **ALE-109 rouverte** (était Done) : audit du code livré (PR #58/#59) → la partie LLM (réutilisation classifications + synthèse via `influencer_cache`/`cached_posts`, service-role) est faite, **mais 2 critères de sa propre DoD ne le sont pas** : `run_analysis` re-scrape **toujours** Apify (`pipeline.py:120-124`), et le cas « rien de neuf → renvoi cache coût ~0 » n'existe pas. Le seul cache du scrape reste le disque `cache/` éphémère sur Render. Commentaire de constat posté sur l'issue.
- **ALE-141 créée** (Medium, sous l'epic ALE-15) : « Opérations IA longues en arrière-plan » — rendre **l'analyse stratégique IA** (`/dashboard/ai-analysis`) et la **génération de posts** (`/generate`) non bloquantes (lancer puis quitter la page, résultat qui apparaît plus tard), sur le modèle de la file `analysis_jobs` (statut persisté + réconciliation, sinon jobs orphelins). Demande Alex.
- **Grise de l'analyse stratégique IA** (`page.tsx`, `GlobalDashboard`) : section « 🧠 Analyse stratégique IA » du dashboard (Veille → Mes influenceurs) **grisée + bouton désactivé** (« Bientôt disponible »), **prod ET dev** (données pas terribles, demande Alex). Endpoint backend `/dashboard/ai-analysis` conservé (réactivable). Code mort retiré (`runAiAnalysis` + états).
- ⚠️ **Déploiement** : PR #84 release `dev → main` mergée le 2026-06-25 → prod (Netlify + Render). Contenu poussé : grise analyse IA + **ALE-132** (fusion dashboard dans « Mes influenceurs ») + **ALE-125** (split backend dev/prod, docs/config). Aucune migration DB, aucune env var.

### 2026-06-24 (ALE-125 : split backend Render dev/prod — symétrie avec Netlify)
- **Objectif** : rétablir la symétrie dev/prod. Avant, 2 sites Netlify (`main`→prod, `dev`→dev) mais **un seul** service Render (sur `main`) → toute modif backend devait être mergée dans `main` pour être testable en ligne (= test en prod). Désormais : `Netlify dev (dev) → Render dev (dev)`.
- **Infra créée (via MCP, le 2026-06-24)** :
  - Nouveau web service Render **`analyseur-linkedin-influenceur-api-dev`** (`srv-d8u1cn5ckfvc73bad8sg`, branche `dev`, plan **free**, région Oregon, même build/start command que la prod). URL : `https://analyseur-linkedin-influenceur-api-dev.onrender.com`. Auto-deploy sur push `dev`.
  - Site Netlify **dev** (`lkd-outreach-dev`, `35a2cf5e`) : `BACKEND_URL` + `NEXT_PUBLIC_BACKEND_URL` repointés du backend prod vers le backend **dev** (tous contextes). Le site prod (`lkd-outreach`, `81f75c05`) reste sur le backend prod.
- **Secrets recopiés sur le service dev** : `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `APIFY_TOKEN`, `APIFY_ACTOR`, `APIFY_PROFILE_ACTOR`, `POSTS_LIMIT`, `ZERNIO_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY` (valeurs depuis `.env` local + clé anon Supabase).
- ⚠️ **Secrets RESTANT à ajouter à la main** sur le service dev (non lisibles via MCP — à copier depuis le dashboard Render prod ou à fournir) : `SUPABASE_SERVICE_ROLE_KEY` (admin/cron), `OPENAI_API_KEY` (génération d'image), `SLACK_CLIENT_ID`/`SLACK_CLIENT_SECRET`/`SLACK_SIGNING_SECRET` (intégration Slack), `APIFY_IG_PROFILE_ACTOR`/`APIFY_IG_REEL_ACTOR` (analyse Instagram). Le web service **boote et fonctionne** sans (analyse LinkedIn + génération + persistance OK) ; seules ces features restent dégradées tant que les secrets ne sont pas ajoutés.
- **Code** : CORS rendu configurable dans `api.py` (`_cors_origins()` + var optionnelle `CORS_ORIGINS`, l'URL du service dev ajoutée aux origines par défaut). Docs (CLAUDE.md tableau d'env + README) mises à jour.
- **Caveat connu (hors scope ALE-125)** : prod et dev partagent encore le **même projet Supabase** → les tests sur dev écrivent dans la même base que la prod. Isolation complète = niveau 2 (2ᵉ projet Supabase), à faire plus tard si la pollution devient un vrai problème.
- ⚠️ **Note** : les **cron jobs** Render (`analyseur-linkedin-scheduler`, `analyseur-daily-ideas`) restent sur `main` (prod uniquement) — non dupliqués sur dev (volontaire).

### 2026-06-21 (job queue : annulation par item + récupération des séries figées)
- **Incident** : une analyse a figé un item à `running` (profil `louisgraffeuil`), « Annuler » ne nettoyait rien → spinner « Analyse en cours » éternel. Cause : le thread de traitement a été tué (redémarrage Render) **pile au lancement** (service redémarré à 12:54:58, item `running` à 12:54:53), et l'annulation ne touchait que la série, jamais les items.
- **Bugs corrigés** (4) :
  1. `cancel_job` (`api.py`) ne soldait que le **job**, pas les items → ajout de `db.cancel_pending_items` (tous les `pending`/`running` → `cancelled`). Le front affiche un spinner pour **toute ligne `running`** indépendamment du statut série, d'où le symptôme.
  2. `process_job` (`src/jobs.py`) **écrasait** un `cancelled` par `done`/`error` en fin de boucle (+ reposait `running` après chaque item) → le thread ne réécrit plus jamais par-dessus un `cancelled` (vérif `get_job_status`/`get_job_item_status` avant chaque écriture). `final_counts` : `failed` ne compte plus que les vrais échecs (cancelled ≠ failed). Nouvelle `final_status(items)`.
  3. **Pas de timeout** : un appel Apify figé bloquait le `_compute_lock` **global** (toutes les séries de tous les users) indéfiniment → `_run_analysis_guarded` borne chaque profil à `ITEM_TIMEOUT_S = 600 s` (run isolé dans un thread jetable, `shutdown(wait=False)` libère le lock).
  4. **Séries orphelines jamais nettoyées** (ex. job `c158b9f0` resté `running` 3/4 depuis le 16/06) → `db.reconcile_stale_jobs` (appelé dans `list_jobs`) solde en `error` les items d'une série active sans update depuis `JOB_STALE_MINUTES = 15`, puis finalise la série. Idempotent.
- **Annulation par item** (demande Alex) : nouvel endpoint `POST /jobs/{job_id}/items/{item_id}/cancel` + bouton « Annuler » sur **chaque ligne** `pending`/`running` (`ItemRow` dans `page.tsx`). Le thread respecte l'annulation d'un item précis sans toucher aux autres. Le front met à jour l'état immédiatement via le job retourné (`onJobUpdated`), sans attendre le polling.
- **Ce que ça règle / ne règle pas** : ça n'empêche pas Apify/Render de planter (externe), mais plus rien ne reste bloqué — timeout (10 min), réconciliation (15 min) ou clic « Annuler » (immédiat) rendent toujours la main.
- **Constat infra Render** (métriques 7 j, backend `srv-d8gn0n7lk1mc73f2pcf0`, plan **free**) : (1) **~40 instances distinctes/semaine** = redémarrages/spin-down constants qui tuent les threads d'analyse = cause #1 des jobs orphelins ; (2) **mémoire à 97-99 % du plafond 512 MiB** dès qu'une analyse tourne (pic 507 MiB le 21/06, 498 MiB le 14/06) → risque d'OOM kill réel. **Reco : passer en Standard (25 $, 2 GiB)** — Starter (7 $) supprime le spin-down mais garde 512 MiB donc ne règle pas l'OOM. Décision reportée par Alex (« la prochaine fois »).
- ⚠️ **Déploiement** : aucun changement DB, aucune env var. À merger `dev → main` (backend Render depuis `main`).

### 2026-06-19 (idée du jour : cron quotidien + réservoir client)
- **Objectif** : une **idée de post générée chaque matin** par utilisateur opt-in, piochée en priorité dans un **réservoir d'idées** que le client remplit lui-même dans l'app (choix in-app + Supabase plutôt que Google Doc : pas de dépendance externe, structuré, RLS automatique).
- **DB** : migration `supabase/migrations/0007_daily_ideas.sql` → tables `idea_seeds` (réservoir, RLS user, `used_at`) + `daily_ideas` (1 idée/jour, `unique(user_id, idea_date)`, **lecture seule côté client** — seul le cron écrit) + colonne `daily_ideas_enabled` (opt-in) sur `user_editorial_profiles`. **À exécuter manuellement dans le SQL editor Supabase.**
- **Service-role (nouveau dans l'archi)** : jusqu'ici tout passait par le JWT user (RLS). Le cron n'a pas de session → ajout d'un **client service-role** dans `db.py` (`admin_client()`/`admin_enabled()`, lit `SUPABASE_SERVICE_ROLE_KEY`). ⚠️ **Réservé au cron, jamais exposé via HTTP** (il bypass la RLS). Helpers cron : `list_daily_idea_users`, `get_corpus_for_user`, `get_ai_context_for_user`, `pop_unused_seed`, `mark_seed_used`, `daily_idea_exists`, `insert_daily_idea`.
- **Cron** : `src/daily_ideas.py` (entrypoint `python -m src.daily_ideas`) — pour chaque user opt-in : reconstruit le benchmark, pioche 1 seed non utilisée (sinon génération pure), `generate_ideas(count=1, seed_topic=…)`, écrit `daily_ideas` + marque la seed. **Idempotent** (skip si l'idée du jour existe déjà), isolé par user (un échec ne bloque pas les autres). Coût = 1 appel Anthropic/user/jour, **pas d'Apify**.
- **Refactor** : `_enrich_influencers` + `_build_benchmark` extraits d'`api.py` vers `src/benchmark.py` (partagés api ↔ cron, comportement inchangé — `api.py` garde des alias).
- **Backend** : `seed_topic` optionnel ajouté à `generate_ideas` (`llm.py`, rétro-compatible). Endpoints `GET/POST /me/idea-seeds`, `DELETE /me/idea-seeds/{id}`, `GET /me/daily-ideas` (idées + état opt-in), `POST /me/daily-ideas/enabled` (tous `require_token`, RLS).
- **Front** (`page.tsx` + `globals.css`) : onglet **« Idée du jour »** (premium/auth) → idée du jour en markdown + historique repliable, **réservoir d'idées** (ajout/suppression) et switch « Recevoir une idée chaque matin ». Composant `DailyIdeasView`.
- **E2E** : test `authenticated.spec.ts` (onglet idée + réservoir + opt-in sans erreur) + « Idée du jour » ajouté au smoke nav.
- ⚠️ **Déploiement** : (1) exécuter la migration 0007, (2) créer un **Cron Job Render** `python -m src.daily_ideas` (schedule conseillé `0 5 * * *` ≈ 6-7h Paris) avec env `ANTHROPIC_API_KEY` + `SUPABASE_URL` + **`SUPABASE_SERVICE_ROLE_KEY`** (nouveau secret), (3) merge `dev → main`. Le service web n'a pas besoin du service-role.

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
