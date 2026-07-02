# Engagement Hunter — Spec Apify (Phase 1)

Workflow de détection de leads LinkedIn **sans connexion compte** — basé sur Apify (scraping anonyme, proxies intégrés).

---

## Actors Apify utilisés

### 1. `harvestapi/linkedin-post-search`

**Rôle** : recherche des posts LinkedIn par mot-clé.

**Input JSON**
```json
{
  "searchQueries": ["<keyword>"],
  "sortBy": "date",
  "postedLimit": "week"
}
```

Mapping `date_posted` Supabase → champ Apify :

| Valeur `monitored_keywords.date_posted` | Valeur input Apify |
|---|---|
| `past_24h` | `24h` |
| `past_week` | `week` |
| `past_month` | `month` |

Valeurs `sortBy` : `"date"` ou `"relevance"` (pas `"date_posted"`).

**Output — champs utiles par item**

| Champ Apify | Type | Notes |
|---|---|---|
| `shareUrn` | string | `urn:li:activity:XXXX` — clé de dédup |
| `entityId` | string | fallback si `shareUrn` absent |
| `linkedinUrl` | string | lien complet du post |
| `content` | string | corps du post |
| `author.name` | string | nom de l'auteur |
| `author.url` | string | URL profil auteur |
| `author.publicIdentifier` | string | slug auteur (pour `author_public_id`) |
| `author.info` | string | headline auteur |
| `author.type` | string | `"company"` si l'auteur est une entreprise |
| `engagement.likes` | int | nombre de likes |
| `engagement.comments` | int | nombre de commentaires |
| `postedAt.date` | ISO 8601 | date de publication |

---

### 2. `scraping_solutions/linkedin-posts-engagers-likers-and-commenters-no-cookies`

**Rôle** : récupère la liste des likers d'un post LinkedIn.

**Input JSON**
```json
{
  "url": "https://www.linkedin.com/feed/update/urn:li:activity:XXXX/",
  "type": "likers",
  "start": 0,
  "iterations": 5
}
```

> ⚠️ Le champ s'appelle `url` (pas `postUrl`). `start` et `iterations` sont requis.

**Output — champs utiles par item**

| Champ Apify | Type | Notes |
|---|---|---|
| `url_profile` | string | `https://www.linkedin.com/in/username/` — clé de dédup leads |
| `name` | string | nom complet |
| `subtitle` | string | headline professionnelle |
| *(pas de location)* | — | non disponible dans cet actor |

> Phase 2 ajoutera `type: "commenters"` en branche parallèle.

---

### 3. `apimaestro/linkedin-profile-batch-scraper-no-cookies-required` *(Phase 2)*

Non utilisé en Phase 1. Prévu pour enrichissement profil (company, role, industry).

---

## Endpoints Apify REST

Non utilisés directement — le node n8n `@apify/n8n-nodes-apify.apify` (operation `"Run actor and get dataset"`) gère run + polling + dataset retrieval en un seul step.

Pour référence :
```
POST https://api.apify.com/v2/acts/{actorSlug}/runs?token={APIFY_TOKEN}
GET  https://api.apify.com/v2/actor-runs/{runId}?token={APIFY_TOKEN}
GET  https://api.apify.com/v2/datasets/{datasetId}/items?token={APIFY_TOKEN}&clean=true
```

---

## Stratégie async : node natif Apify

Le node `@apify/n8n-nodes-apify.apify` avec l'opération `"Run actor and get dataset"` :
1. Lance le run Apify
2. Poll automatiquement jusqu'à `SUCCEEDED`
3. Retourne les items du dataset directement comme items n8n

> **Note n8n** : timeout du node ≥ 300s recommandé (n8n → Settings → `execTimeout`).

---

## Mapping champs Apify → Supabase

### `harvestapi` posts → `monitored_posts`

| Source | Colonne Supabase | Transformation |
|---|---|---|
| `shareUrn` \| `entityId` \| `id` \| `linkedinUrl` | `social_id` | clé de dédup UNIQUE |
| `linkedinUrl` | `share_url` | |
| `content` | `text_content` | `.slice(0, 5000)` |
| `author.publicIdentifier` ou slug extrait de `author.url` | `author_public_id` | regex `/\/in\/([^/?]+)/` |
| `author.name` | `author_name` | |
| `author.info` | `author_headline` | |
| `author.type === 'company'` | `author_is_company` | |
| `engagement.likes` | `reaction_counter` | |
| `engagement.comments` | `comment_counter` | |
| `postedAt.date` | `parsed_datetime` | |
| `keyword.id` (contexte loop) | `monitored_keyword_id` | |

### `scraping_solutions` engagers → `leads`

| Source | Colonne Supabase | Valeur |
|---|---|---|
| `name` | `name` | nom complet |
| `subtitle` | `headline` | |
| `url_profile` | `linkedin_profile_url` | clé de dédup |
| hardcodé | `location` | `null` (non disponible) |
| hardcodé | `signal` | `"engaged-content"` |
| `"A liké un post sur \"<keyword>\""` | `signal_text` | templated |
| `keyword.id` (contexte loop) | `monitored_keyword_id` | |
| `post.id` (row Supabase retourné après upsert) | `source_post_id` | |
| hardcodé | `engagement_type` | `"reaction"` |
| hardcodé | `status` | `"to-validate"` |
| hardcodé | `score` | `2` |
| hardcodé | `invitation_connection` | `"non envoyée"` |

---

## Dédoublonnage

| Entité | Mécanisme |
|---|---|
| `monitored_posts` | Upsert Supabase avec `?on_conflict=social_id` + `Prefer: resolution=merge-duplicates` |
| `leads` | GET Supabase avant INSERT : skip si `linkedin_profile_url` déjà présent |
| Engagers déjà traités | `engagers_fetched_at` sur la row post : skip si `< 24h` (via IF node après upsert) |

---

## Credentials requis

| Variable | Valeur | Où configurer |
|---|---|---|
| Apify token | Token Apify (onglet Settings → API) | n8n Credentials → "Apify account" (type `apifyApi`) |
| `SUPABASE_URL` | `https://zqrwurcxlumkkuzhwnzg.supabase.co` | Config node (pré-rempli) |
| `SUPABASE_SERVICE_KEY` | Service role JWT (Supabase → Settings → API) | Config node (ligne 2) **à remplir** |

Le token Apify n'est pas dans le Config node — il passe par le credential n8n (`id: N3tJdqGkSCIgaiEJ`).

---

## Migration Supabase

**Migration 003 non nécessaire pour Phase 1.** Toutes les colonnes requises existent dans `migration_001` + `migration_002` :
- `leads` : `name`, `headline`, `linkedin_profile_url`, `location`, `signal`, `signal_text`, `score`, `status`, `engagement_type`, `monitored_keyword_id`, `source_post_id`, `invitation_connection`
- `monitored_posts` : `social_id` (UNIQUE), `share_url`, `text_content`, `author_*`, `reaction_counter`, `comment_counter`, `parsed_datetime`, `engagers_fetched_at`, `monitored_keyword_id`

---

## Schéma du workflow

```
[Manual Trigger]
[Schedule 1×/jour 6h00]
        ↓
    [Config]
        ↓
[GET monitored_keywords WHERE is_active=true]
        ↓
[Code: split array → N items]
        ↓
[Loop keywords] ←─────────────────────────────────────────────────────┐
   │ (loop)                                                            │
   ↓                                                                   │
[Apify: harvestapi/linkedin-post-search]                               │
  (Run actor and get dataset — node natif Apify)                       │
        ↓                                                              │
[Code: normalize posts → M items]                                      │
        ↓                                                              │
[Loop posts] ←────────────────────────────────────────────────────┐   │
   │ (loop)                            (done) → [Update keyword]──┘   │
   ↓                                            last_run_at=now()  ───┘
[POST Supabase upsert monitored_posts]
        ↓
[Code: unwrap upsert response + check engagers_fetched_at]
        ↓
[IF should_fetch_engagers?]
   │ YES                  │ NO (engagers < 24h) ─────────────────────→ [Loop posts]
   ↓                                                                    (advance)
[Apify: scraping_solutions/linkedin-posts-engagers-likers-and-commenters-no-cookies]
  (Run actor and get dataset — node natif Apify)
        ↓
[Code: normalize engagers → K items]
        ↓
[Loop engagers] ←────────────────────────────────────────────────────────────────┐
   │ (loop)                 (done) → [PATCH monitored_posts engagers_fetched_at] ┘
   ↓                                  → [Loop posts] (advance)
[GET leads WHERE linkedin_profile_url = X]
        ↓
[IF result empty (nouveau lead)?]
   │ YES                  │ NO ──────────────────┐
   ↓                                             ↓
[POST leads]                               [Skip (NoOp)]
   { name, headline, linkedin_profile_url,      │
     signal: "engaged-content",                 │
     signal_text: "A liké un post sur ...",     │
     monitored_keyword_id, source_post_id,      │
     engagement_type: "reaction",               │
     status: "to-validate", score: 2 }          │
        └──────────────────────────────────────→ [Loop engagers] (advance)
```
