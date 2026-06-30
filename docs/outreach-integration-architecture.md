# Doc d'archi — Module Outreach LinkedIn dans l'Analyseur

> Rédigé le 2026-06-30. Objectif : intégrer un module d'outreach LinkedIn type **HeyReach** (détecter des leads chauds → envoyer invitations/messages sans se faire ban) **dans l'app Analyseur existante**, en reprenant les idées/UI/schéma de l'ancien projet **Polaris** (`CascadeProjects/linkedin-outreach/polaris/`) mais posés sur l'infra déjà en place de l'Analyseur.
>
> Ce doc sert de base pour créer l'épic + les issues Linear. Il liste les fichiers à créer/modifier, le schéma, et la conception du moteur anti-ban.

---

## 0. Principe directeur (repris de Polaris, il est juste)

On **sépare la détection de l'action** :

```
DÉTECTION (sans compte LinkedIn connecté)  →  Apify (scraping anonyme, no-cookies)
ACTION    (avec compte LinkedIn connecté)  →  Unipile (invitations + messages)
```

Argument commercial : « essaie sans connecter ton LinkedIn ; on le branche seulement quand tu valides les leads et veux envoyer ». La détection ne coûte qu'Apify ; l'action n'arrive qu'après validation.

**Signal d'intention = Engagement Hunter** : on surveille des mots-clés, on récupère les gens qui likent/commentent les posts qui en parlent → ce sont des leads chauds.

**Le cœur de valeur (et de risque) = le moteur d'envoi anti-ban.** C'est la seule grosse brique qui n'a JAMAIS été codée dans Polaris (uniquement spécifiée). Unipile **n'impose aucune limite** côté serveur → tout le cadençage doit être codé chez nous.

---

## 1. Ce qu'on réutilise tel quel dans l'Analyseur

| Besoin outreach | Brique Analyseur existante | Fichiers de référence |
|---|---|---|
| Scraper les engagers en tâche de fond | File de jobs (`analysis_jobs`/`analysis_job_items`) : thread de fond, lock, timeout, réconciliation, annulation par item | `src/jobs.py:78-162`, `src/db.py:954-1236` |
| Moteur d'envoi cadencé | Crons Render service-role (scheduler tourne déjà `*/5 * * * *`) | `src/scheduler.py`, `src/daily_ideas.py`, `db.admin_client()` (`db.py:69-79`) |
| Connecter un compte externe | Pattern Zernio (profil + account_id stockés sur `user_editorial_profiles`) | `src/zernio.py:161-222`, `api.py:388-431`, `db.set_zernio_account` (`db.py:489-507`) |
| Valider un message avant envoi | Boutons Slack ✅/❌ + webhook callback qui MAJ le statut | `src/slack.py:357-451`, `api.py:1654-1790` |
| Générer le message | Client Anthropic + tracking usage | `src/llm.py:41-273` (`_client()`, `_model()`, `_track()`) |
| Nouvel onglet UI | `view` state + sidebar + gating auth/premium | `frontend/app/page.tsx` (`mainViews` l.218, `view` l.5508, `requireAuth` l.5573) |
| RLS par utilisateur | `using ((select auth.uid()) = user_id)` | migrations `0001`, `0025` |

→ **La seule brique vraiment neuve = Unipile (`src/unipile.py`) + le moteur de quotas/warm-up/freeze (logique pure).**

---

## 2. Modèle de données — migration `0026_outreach.sql`

> ⚠️ Vérifier le **prochain numéro libre au moment du merge** (la mémoire indiquait 0021 le 24/06, l'exploration trouve 0025 ; des PR parallèles peuvent décaler). Toutes les tables : `user_id uuid references auth.users`, RLS `auth.uid() = user_id`, idempotentes (`if not exists`).

On porte le schéma Polaris **scopé par `user_id`** (Polaris était mono-user, RLS permissive — ici on durcit d'emblée), et on ajoute les tables propres au moteur d'envoi.

### Détection (repris de Polaris)
- **`monitored_keywords`** : `keyword`, `description`, `is_active`, `date_posted` (past_24h|past_week|past_month), `content_type`, `author_keywords`, `sort_by`, `posts_found_total`, `leads_found_total`, `last_run_at`, `last_error`, `user_id`.
- **`monitored_posts`** : `social_id` (UNIQUE, dedup), `share_url`, `text_content`, `author_*`, `reaction_counter`, `comment_counter`, `parsed_datetime`, `monitored_keyword_id` (FK), `engagers_fetched_at`, `engagers_count`, `user_id`.
- **`outreach_leads`** (= `leads` de Polaris, renommé pour ne pas confondre avec d'éventuelles autres tables) : `name`/`first_name`/`last_name`, `headline`, `role`, `company_name`, `linkedin_profile_url` (dedup par user), `signal`, `signal_text`, `score` (1-3), `status` (to-validate|in-progress|replied), `engagement_type` (reaction|comment), `monitored_keyword_id`, `source_post_id`, `proposed_message`, `user_id`.

### Action / anti-ban (NEUF)
- **`outreach_accounts`** — 1 ligne par compte LinkedIn connecté via Unipile, porte tout l'état anti-ban :
  - identité : `unipile_account_id`, `connected_at`, `timezone`
  - warm-up : `warmup_started_at`, (le palier courant se calcule depuis cette date)
  - quotas config : `daily_cap_invites`, `weekly_cap_invites`, `daily_cap_messages`, `weekly_cap_messages`
  - fenêtre horaire : `working_hours_start`, `working_hours_end`, `working_days`
  - compteurs glissants : `invites_sent_today`, `invites_sent_week`, `messages_sent_today`, `messages_sent_week`, `counters_reset_at`
  - sécurité : `frozen` (bool), `freeze_reason`, `last_action_at`
- **`outreach_actions`** — la file d'envoi (une ligne = une action à faire) :
  - `lead_id` (FK), `account_id` (FK), `type` (invitation|message), `body` (texte généré)
  - `status` (pending → awaiting_validation → approved → sent | failed | skipped)
  - `scheduled_for`, `sent_at`, `error`, `unipile_response`, `slack_message_ts`, `user_id`

(Optionnel phase détection-batch : `detection_jobs`/`detection_job_items` calqués sur `analysis_jobs` si on veut un déclenchement manuel par lot. Sinon la détection est un simple cron.)

---

## 3. Le moteur anti-ban (la pièce critique — copie de HeyReach)

Implémenté dans **`src/outreach_sender.py`** (entrypoint `python -m src.outreach_sender`, cron Render `*/10 * * * *`), service-role, calqué sur `src/scheduler.py`.

**Chiffres à respecter (HeyReach / Unipile) :**
- Invitations : **20/j au départ → plafond 100-150/semaine**. ⚠️ Avec note d'invitation : **~10/mois** seulement → **on envoie sans note par défaut**.
- Messages : **40/j → ~100-120/semaine**.
- Warm-up : compte neuf/inactif → **3 semaines à 20-30 actions/j** avant de monter.
- Délais aléatoires entre actions ; **horaires de bureau** uniquement.
- **Freeze automatique** près du plafond hebdo (non contournable) — c'est ça qui protège le compte.

**Logique d'un tick de cron (par `outreach_account`) :**
1. `frozen` ? → skip.
2. Hors `working_hours` / `working_days` (selon `timezone`) ? → skip.
3. Reset des compteurs `today`/`week` si la période a tourné.
4. Calculer le **palier de warm-up** depuis `warmup_started_at` (sem.1 = 20/j, sem.2 = 40/j, sem.3+ = plafond config), borné par les caps config.
5. Cap quotidien OU hebdo atteint ? → skip (et `frozen=true` si on frôle le plafond hebdo).
6. Délai aléatoire min depuis `last_action_at` pas écoulé ? → skip ce tick.
7. Sinon : prendre **1 à N actions `approved`** (N petit, ex. 1-3), les envoyer via `src/unipile.py`, incrémenter les compteurs, MAJ `last_action_at`.
8. Gestion d'erreur Unipile : `422 / cannot_resend_yet` → `frozen=true` + `freeze_reason`, on arrête pour ce compte.

> Les caps sont des **plafonds durs côté serveur**, jamais contournables par l'UI. C'est le point non négociable.

---

## 4. Détection — `src/outreach_detector.py` (Engagement Hunter)

Cron Render (ex. `0 6 * * *`) **OU** déclenché via la file de jobs pour un run manuel. Réutilise la plomberie **Apify déjà présente** dans l'Analyseur.

Par utilisateur opt-in → par `monitored_keyword` actif :
1. Apify `harvestapi/linkedin-post-search` (input : `searchQueries`, `sortBy`, `postedLimit`) → upsert `monitored_posts` (dedup `social_id`).
2. Pour chaque post (skip si `engagers_fetched_at < 24h`) : Apify `scraping_solutions/linkedin-posts-engagers-...-no-cookies` (`type: likers`) → engagers.
3. Filtre ICP (titres/industries/tailles/localisations de la stratégie) → insert `outreach_leads` (`status='to-validate'`, `signal='engaged-content'`, dedup par `linkedin_profile_url`).
4. PATCH `monitored_keywords` (`last_run_at`, `leads_found_total`).

> **On n'utilise PAS le n8n legacy.** Le JSON Polaris ne sert que de référence d'endpoints. Tout vit dans le backend Python pour rester sur l'infra cron+jobs déjà éprouvée et maîtriser les garde-fous.

---

## 5. Découpage en issues (1 issue = 1 branche = 1 PR, base `dev`)

| # | Issue | Livrable visible | Fichiers principaux | Effort |
|---|---|---|---|---|
| 1 | **Schéma + détection** | Un mot-clé créé → des leads chauds apparaissent | `0026_outreach.sql`, `src/outreach_detector.py`, helpers `db.py`, endpoints `/outreach/keywords` + `/outreach/leads` dans `api.py`, cron Render | M-L |
| 2 | **UI Veille/Prospects** | Onglet outreach : stratégie/ICP + mots-clés + liste de leads (realtime) | `frontend/app/page.tsx` (`OutreachView`), portage `KeywordsCard`, génération message via `src/llm.py` | M |
| 3 | **Connexion Unipile** | Bouton « connecter mon LinkedIn » + compte stocké | `src/unipile.py`, endpoints `/outreach/connect|status|disconnect`, colonnes `outreach_accounts` | M |
| 4 | **Moteur anti-ban + envoi** | Une action validée part en respectant quotas/warm-up/freeze | `src/outreach_sender.py` (cron), client Unipile send, file `outreach_actions` | **L (critique)** |
| 5 | **Validation des messages** | Message généré → validé (Slack ou in-app) → envoyé | réutilise `src/slack.py` + webhook `api.py`, statuts `outreach_actions` | M |
| 6 | **Messagerie + stats** | Réponses lues, taux de réponse réel | webhook Unipile entrant, tables conversations, page stats | L (plus tard) |

Ordre conseillé : **1 → 2 → 3 → 4 → 5**, puis 6 après PMF. Les phases 1-2 livrent déjà de la valeur (détection seule, sans risque de ban).

---

## 6. Points de vigilance

- **Plafonds durs serveur** : jamais d'override UI sur les caps. C'est la garantie anti-ban.
- **Sans note d'invitation par défaut** (la limite avec note est tombée à ~10/mois).
- **Compte LinkedIn réel et mature** (>150 connexions) requis — à dire dans l'onboarding.
- **Supabase prod/dev partagé** (caveat connu de l'Analyseur) : les tests dev écrivent dans la même base. Scoper proprement par `user_id`.
- **Secrets Render à ajouter** : `UNIPILE_DNS`, `UNIPILE_API_KEY` (prod + service dev). `SUPABASE_SERVICE_ROLE_KEY` déjà requis par les crons existants.
- **Stratégie/ICP** : Polaris la gardait en localStorage. Ici → la persister en DB (table `outreach_settings` ou colonnes) pour le multi-user et pour que le cron de détection y accède côté service-role.
- **Migration numéro** : revérifier le prochain libre au merge (règle CLAUDE.md).

---

## 7. Ce qu'on récupère vs ce qu'on recode

- **Récupéré de Polaris** : schéma de données, prompts IA (`preview-message`, `parse-target`, `extract-rule`, `reply-draft`), UI (prospects, stratégie, autopilot par étapes), specs Apify/Unipile.
- **Recodé sur l'infra Analyseur** : tout le câblage backend (Python au lieu de routes Next + n8n), la connexion Unipile, et surtout **le moteur anti-ban** (inédit).
- **Jeté** : les workflows n8n legacy (référence d'endpoints seulement), la persistance localStorage, les RLS permissives.
