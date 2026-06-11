# LinkedIn Strategy Decoder

Analyse la stratégie de contenu d'un profil LinkedIn : fréquence, timing, mix de formats, mix funnel TOFU/MOFU/BOFU, hooks récurrents, et actions à répliquer.

Sortie : un rapport Markdown dans `reports/`.

## Pipeline

1. **Scraping profil** — `supreme_coder/linkedin-profile-scraper` → followers, headline, mode créateur, badge influenceur.
2. **Scraping posts** — `apimaestro/linkedin-profile-posts` (ou `harvestapi/linkedin-company-posts`) récupère les N derniers posts.
3. **Normalisation** — schéma unifié, multi-actors (gère `engagement.likes` imbriqué et clés plates).
4. **Stats déterministes** — pandas : fréquence, distribution jour/heure, mix de formats, **médianes** d'engagement, **top 5 par commentaires**, **taux d'engagement vs followers**, exclusion des posts <24h.
5. **Détection de patterns** (regex/heuristiques) :
   - **CTA commentaires** : "Commente 'MOT'", "Commentez X" → comparaison médianes avec/sans CTA.
   - **Type de hook** sur la 1ère ligne : `stat`, `list`, `question`, `contrarian`, `result`, `bold_claim`, `story`.
   - **Signatures visuelles** récurrentes (↳, →, •, ✓…).
   - **Sections récurrentes** (titres en bold ou `Section :`).
6. **Classification LLM** — TOFU/MOFU/BOFU par post (Claude, JSON strict).
7. **Synthèse LLM** — positionnement, piliers, patterns, forces/manques, actions concrètes.
8. **Compteurs usage** — runs/items Apify, tokens Anthropic, coûts estimés par analyse.
9. **Rapport Markdown** dans `reports/<handle>-<timestamp>.md`.

## TOFU / MOFU / BOFU

- **TOFU — Top of Funnel** : contenu d'attraction. Storytelling, opinions, posts viraux, sujets larges, prises de position. Objectif : toucher de nouvelles audiences.
- **MOFU — Middle of Funnel** : contenu d'éducation. Méthodes, frameworks, tutoriels, cas d'usage, expertise. Objectif : faire comprendre le problème et construire la confiance.
- **BOFU — Bottom of Funnel** : contenu de conversion. Preuves, offres, témoignages, CTA commerciaux, posts orientés vente ou prise de rendez-vous. Objectif : déclencher une action business.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# remplir APIFY_TOKEN et ANTHROPIC_API_KEY
```

## Usage

### Interface web (recommandé)

```bash
streamlit run app.py
```

→ ouvre `http://localhost:8501`. Form, KPIs, onglets (rapport, top posts, patterns, posts bruts), historique des analyses dans la sidebar.

### CLI

```bash
python3 analyze.py https://linkedin.com/in/nom-influenceur
python3 analyze.py https://linkedin.com/in/nom-influenceur --limit 50 --no-cache
```

Les posts bruts sont mis en cache dans `cache/<handle>.json` pour éviter de re-payer Apify entre runs.

## Coût indicatif

- Apify (`supreme_coder/linkedin-profile-scraper` + `apimaestro/linkedin-profile-posts`) : ~$0.005–0.01 / analyse.
- Anthropic `claude-opus-4-7` : ~$0.30–0.80 par profil (2 appels, ~10k tokens). Pour réduire ~5× utilise `claude-sonnet-4-6` via `ANTHROPIC_MODEL`.
- Total : **~$0.30–0.80 / analyse en Opus 4.7**, ~$0.05–0.15 en Sonnet 4.6.

## Configuration

Variables `.env` :

| Var | Défaut | Description |
|---|---|---|
| `APIFY_TOKEN` | — | Token Apify (requis) |
| `ANTHROPIC_API_KEY` | — | Clé Anthropic (requise pour la synthèse) |
| `ANTHROPIC_MODEL` | `claude-opus-4-7` | Modèle Claude (`claude-sonnet-4-6` pour économiser ~5×) |
| `APIFY_ACTOR` | `apimaestro/linkedin-profile-posts` | Actor posts (supporte aussi `harvestapi/linkedin-company-posts`) |
| `APIFY_PROFILE_ACTOR` | `supreme_coder/linkedin-profile-scraper` | Actor profil |
| `POSTS_LIMIT` | `30` | Nb max de posts |

## Base de données (Supabase)

App multi-utilisateurs : chaque utilisateur a son propre espace (analyses, influenceurs, posts) isolé par **Row Level Security**.

### Projet

| Champ | Valeur |
|---|---|
| Projet | `Linkedin analyse` (`zcxaxwqkswuefzlzpgvi`, eu-west-1) |
| URL | `https://zcxaxwqkswuefzlzpgvi.supabase.co` |

### Schéma (`public`)

| Table | Rôle |
|---|---|
| `profiles` | Profil applicatif lié à `auth.users` (créé automatiquement à l'inscription via trigger) |
| `influencers` | Influenceurs analysés, scoping `user_id`, unique `(user_id, handle)` |
| `posts` | Posts normalisés rattachés à un influenceur (cascade delete) |
| `analyses` | Rapport + données calculées (`stats`, `patterns`, `synthesis`, `usage`…) par run |

RLS activée sur toutes les tables : un utilisateur ne lit/écrit que ses propres lignes (`user_id = auth.uid()`).

### Variables d'environnement

Backend (FastAPI / Render) :

| Var | Description |
|---|---|
| `SUPABASE_URL` | `https://zcxaxwqkswuefzlzpgvi.supabase.co` |
| `SUPABASE_ANON_KEY` | Clé anon/publishable du projet |

Frontend (Next.js / Netlify) — optionnel, valeurs publiques par défaut dans `app/lib/supabase.ts` :

| Var | Description |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | URL du projet Supabase |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Clé anon (sûre à exposer côté navigateur) |

### Fonctionnement

- Le frontend gère l'auth via `@supabase/supabase-js` (`AuthGate` : login / signup / logout).
- Chaque requête `/analyze` envoie le JWT en `Authorization: Bearer <token>`.
- Si un JWT valide est présent, le backend **persiste l'analyse en BDD** (best-effort, n'échoue jamais l'analyse). Sinon, comportement fichier inchangé.
- Endpoints utilisateur : `GET /me/influencers`, `GET /me/analyses`, `GET /me/analyses/{id}` (auth requise).

## Déploiement production

### URLs

| Service | URL |
|---|---|
| Frontend Netlify | https://lkd-outreach.netlify.app |
| Backend Render | https://analyseur-linkedin-influenceur-api.onrender.com |
| Health backend | https://analyseur-linkedin-influenceur-api.onrender.com/health |
| GitHub | https://github.com/Xprriacst/analyseur-linkedin-influenceur |

### Comptes et services

| Plateforme | Compte / workspace | Service |
|---|---|---|
| Render | `Alex's workspace` — `contact.polaris.ia@gmail.com` | `analyseur-linkedin-influenceur-api` |
| Netlify | `Xprriacst’s team` | `courageous-strudel-2d8ba3` |

### Render backend

Service Render :

```txt
https://dashboard.render.com/web/srv-d8gn0n7lk1mc73f2pcf0
```

Configuration :

| Champ | Valeur |
|---|---|
| Runtime | Python |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn api:app --host 0.0.0.0 --port $PORT` |
| Branch | `main` |
| Auto deploy | Activé |

Variables d'environnement Render requises :

| Var | Description |
|---|---|
| `APIFY_TOKEN` | Token Apify utilisé par le scraper |
| `ANTHROPIC_API_KEY` | Clé Anthropic utilisée par la synthèse/génération |
| `ANTHROPIC_MODEL` | Modèle Claude, actuellement `claude-sonnet-4-6` |

Vérification attendue :

```bash
curl https://analyseur-linkedin-influenceur-api.onrender.com/health
```

Réponse attendue :

```json
{
  "ok": true,
  "apify": true,
  "anthropic": true,
  "model": "claude-sonnet-4-6"
}
```

### Netlify frontend

Site Netlify :

```txt
https://app.netlify.com/projects/courageous-strudel-2d8ba3
```

Variable d'environnement Netlify requise en production :

| Var | Valeur |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://analyseur-linkedin-influenceur-api.onrender.com` |

Le frontend Next.js lit cette variable dans `frontend/app/page.tsx`. Si elle manque au build Netlify, le frontend retombe sur `http://localhost:8000`.

Commande CLI utilisée pour définir la variable :

```bash
netlify env:set NEXT_PUBLIC_API_URL https://analyseur-linkedin-influenceur-api.onrender.com --context production
```

Après modification d'une variable `NEXT_PUBLIC_*`, redéployer Netlify :

```bash
netlify deploy --prod
```

Vérification du bundle publié :

```bash
curl -sS https://lkd-outreach.netlify.app/_next/static/chunks/app/<page-chunk>.js | grep "analyseur-linkedin-influenceur-api.onrender.com"
```

### CORS

Le backend FastAPI autorise explicitement le frontend Netlify dans `api.py` :

```txt
https://lkd-outreach.netlify.app
```

## Structure

```
app.py                # interface Streamlit
analyze.py            # entrypoint CLI
src/
  scraper.py          # Apify (profil + posts) + cache
  normalize.py        # unification multi-schéma (posts + profil)
  stats.py            # stats déterministes + médianes + CTA breakdown
  patterns.py         # détection CTA / hook / signature / sections
  usage.py            # compteurs Apify + Anthropic + coûts estimés
  llm.py              # classifications TOFU/MOFU/BOFU + synthèse Claude
  report.py           # rendu Markdown (4 blocs)
reports/              # rapports générés
cache/                # cache des scrapes (profile + posts séparés)
```

## Notes

- Si tu changes d'actor Apify, le `run_input` peut différer ; ajuste `src/scraper.py`.
- `src/normalize.py` tolère plusieurs schémas (`text`/`postText`, `numLikes`/`likes`, etc.). Vérifie un post brut dans `cache/` si la normalisation rate.
- Les classifications/synthèses demandent à Claude de répondre en JSON strict ; `src/llm.py` extrait le JSON si Claude ajoute quand même du texte.
