# Référence outreach — artefacts repris du projet Polaris

Ces fichiers sont une **copie de référence en lecture seule** issue de l'ancien prototype Polaris
(`linkedin-outreach/polaris/`, repo séparé). Ils sont vendorés ici pour que le module outreach
de l'Analyseur (épic ALE-168) soit **auto-suffisant** : un agent qui implémente une issue n'a
PAS besoin d'accéder au projet Polaris.

> ⚠️ Ne pas exécuter ni importer tel quel. Polaris est en Next.js + Supabase mono-user avec RLS
> permissive. Côté Analyseur on **réimplémente** en backend Python, scopé `user_id`, RLS stricte.
> Ces fichiers servent de **modèle** (schéma, prompts, specs), pas de code à copier-coller.

## Contenu

### `sql/` — schéma de données (modèle à porter dans la migration `0026`)
- `migration_001_core_tables.sql` — tables `companies`, `sales_searches`, `leads`
- `migration_002_engagement_hunter.sql` — `monitored_keywords`, `monitored_posts` + colonnes engagement sur `leads`

À porter en : `monitored_keywords`, `monitored_posts`, `outreach_leads`, scopés `user_id`,
RLS `auth.uid() = user_id`, idempotentes. Voir `../outreach-integration-architecture.md` §2.

### `ai-prompts/` — prompts IA (à réimplémenter via `src/llm.py`)
- `prompts.ts` — system prompt d'onboarding + tool `propose_strategy`
- `preview-message.route.ts` — génération du 1er message (ton, neverDo, signal, règles apprises)
- `parse-target.route.ts` — phrase libre ICP → chips (titres/industries/tailles/localisations), forced tool-use
- `extract-rule.route.ts` — diff d'édition → règle de style généralisable
- `reply-draft.route.ts` — réponse contextuelle dans une conversation

### `specs/` — specs détection (endpoints Apify/Unipile exacts)
- `ENGAGEMENT_HUNTER_SPEC.md` — version Unipile native (endpoints search/reactions/comments/profile)
- `ENGAGEMENT_HUNTER_APIFY_SPEC.md` — version Apify no-cookies (actors + inputs/outputs + mapping vers le schéma)

## Doc d'archi principal
`../outreach-integration-architecture.md` — plan d'intégration, mapping des briques Analyseur
réutilisées, conception du moteur anti-ban, découpage en issues.
