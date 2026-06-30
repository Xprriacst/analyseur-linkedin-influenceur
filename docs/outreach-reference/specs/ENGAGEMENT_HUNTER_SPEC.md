# Workflow n8n — Engagement Hunter

Workflow de prospection **sans Sales Navigator**, basé sur l'engagement des posts LinkedIn (approche Gojiberry).

## Principe

1. Polaris stocke des **mots-clés à surveiller** dans `monitored_keywords`
2. n8n tourne en cron, search les posts LinkedIn classiques contenant ces mots-clés via Unipile
3. Pour chaque post : récupère la liste des **likers** + **commenters**
4. Pour chaque engager : enrichit le profil, filtre par ICP de la stratégie, insère dans `leads`
5. Polaris affiche les nouveaux leads en realtime

## Pré-requis

- Compte LinkedIn classique (pas Sales Nav requis)
- Compte Unipile avec ce LinkedIn connecté → `account_id`
- Credentials n8n : Header Auth `X-API-KEY` (Unipile)
- Variables d'env n8n : `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `UNIPILE_DNS`, `UNIPILE_ACCOUNT_ID`

## Schéma du workflow

```
[Cron: every 6h]
   ↓
[GET monitored_keywords WHERE is_active=true]
   ↓
[Loop over keywords]
   ↓
[POST {unipile_dns}/api/v1/linkedin/search]
   body: {
     api: "classic",
     category: "posts",
     keywords: "{{kw.keyword}}",
     date_posted: "{{kw.date_posted}}",
     sort_by: "{{kw.sort_by}}",
     content_type: "{{kw.content_type}}",  // si défini
     author: { keywords: "{{kw.author_keywords}}" }  // si défini
   }
   query: { account_id: "{{kw.linkedin_account ?? UNIPILE_ACCOUNT_ID}}" }
   ↓
[Loop over posts]
   ↓
[Upsert into monitored_posts]
   (clé: social_id)
   ↓
[GET {unipile_dns}/api/v1/posts/{social_id}/reactions?account_id=X]
   ↓
[GET {unipile_dns}/api/v1/posts/{social_id}/comments?account_id=X]
   ↓
[Merge engagers + dedupe by profile_id]
   ↓
[Loop over engagers]
   ↓
[GET {unipile_dns}/api/v1/users/{profile_id}?account_id=X]
   (récupère profil complet : name, headline, current company, location)
   ↓
[Filter by ICP (Code node)]
   - read polaris-strategy chips (titles, industries, sizes, locations)
   - matche le profil contre ces critères
   - skip si pas de match
   ↓
[POST supabase /rest/v1/leads]
   body: {
     name, headline, linkedin_profile_url,
     signal: 'engaged-content',
     signal_text: 'A {{reaction|comment}} un post sur "{{keyword}}"',
     monitored_keyword_id: kw.id,
     source_post_id: post.id,
     engagement_type: 'reaction' | 'comment',
     status: 'to-validate',
     score: 2  // calculer selon force du signal
   }
   ↓
[PATCH monitored_keywords SET leads_found_total = leads_found_total + N]
   ↓
[PATCH monitored_keywords SET last_run_at = now()]
```

## Endpoints Unipile utilisés

| Endpoint | Doc |
|---|---|
| `POST /api/v1/linkedin/search` (api=classic, category=posts) | https://developer.unipile.com/docs/linkedin-search |
| `GET /api/v1/posts/{social_id}/reactions` | https://developer.unipile.com/reference/postscontroller_listallreactions |
| `GET /api/v1/posts/{social_id}/comments` | https://developer.unipile.com/reference/postscontroller_listallcomments |
| `GET /api/v1/users/{provider_id}` | https://developer.unipile.com/reference/userscontroller_getprofile |

## Dédoublonnage

- `monitored_posts.social_id` UNIQUE → un post traité une seule fois
- Avant insert dans `leads` : vérifier que `member_urn` ou `linkedin_profile_url` n'existe pas déjà
- Stocker `engagers_fetched_at` pour ne pas re-fetcher les engagers d'un post < 24h

## Rate limiting

- LinkedIn classique : ~50-100 actions/jour selon maturité du compte
- Wait random `5-12s` entre chaque appel `/users/{id}` et `/posts/{id}/reactions`
- Limiter à **20 nouveaux leads/jour** par compte LinkedIn (paramétrable plus tard via `weekly_quotas` table)

## Migration depuis l'ancien workflow

L'ancien workflow `Scrap_SalesNav_Supabase.json` reste dans le repo mais n'est plus utilisé.
Si tu veux le réactiver pour des clients qui ont Sales Nav, c'est possible — les deux peuvent coexister
(un lead peut avoir soit `sales_search_id`, soit `monitored_keyword_id` selon sa source).
