# Tests E2E de non-régression (Playwright)

Suite de smoke tests qui tourne contre le **site dev déployé** (`lkd-outreach-dev.netlify.app`)
avec un compte Supabase de test. **Lecture seule** : aucun test ne déclenche de génération
(pas de coût Anthropic/Apify) ni de publication LinkedIn.

## Lancer

```bash
cd e2e
npm install
npx playwright install chromium   # première fois seulement
npx playwright test               # tout
npx playwright test --headed      # avec navigateur visible
npx playwright show-report        # rapport HTML du dernier run
```

## Configuration

Surchargeable par variables d'env (voir `.env.example`) :

| Var | Défaut |
|---|---|
| `E2E_BASE_URL` | `https://lkd-outreach-dev.netlify.app` |
| `E2E_EMAIL` | `qa.playwright@lkd-outreach.app` |
| `E2E_PASSWORD` | `Lkd!Test2026` |

Pour tester la prod : `E2E_BASE_URL=https://lkd-outreach.netlify.app npx playwright test`.

## Structure

- `tests/auth.setup.ts` — se connecte une fois, persiste la session (`playwright/.auth/user.json`).
- `tests/smoke.spec.ts` — écrans publics (sans login).
- `tests/authenticated.spec.ts` — onglets Profil / Mes contenus / Générateur / Assistant.
- `tests/helpers.ts` — `login()` + `gotoTab()`.

## Test manuel (avant release)

Ce que l'auto ne couvre pas (génération réelle, publication, persistance après refresh) :
voir **`MANUAL-CHECKLIST.md`**.

## Isolation cross-compte (opt-in, génère)

Projet `isolation` (`tests/cross-user-isolation.spec.ts`) : non-régression de la **fuite de
données entre comptes** (PR #102). Connecte le compte A, génère un lot d'idées, bascule sur
le compte B **dans le même onglet sans recharger**, et vérifie que B ne voit rien de A.

⚠️ Ce test **génère réellement** (1 appel Anthropic, ~centimes) → exclu du smoke read-only.
Lancer à la demande :

```bash
npx playwright test --project=isolation
```

Prérequis : 2 comptes de test (A = compte qa par défaut avec ≥1 influenceur analysé ;
B = `qa.playwright.b@lkd-outreach.app` / `Lkd!Test2026`). Surcharges : `E2E_EMAIL_B` /
`E2E_PASSWORD_B`. Les deux comptes doivent avoir un profil éditorial (sinon l'onboarding
plein écran intercepte les clics).

## Pistes (opt-in, coûteux)

Tests de **génération réelle** (idées, posts, analyse) non inclus car ils consomment des
crédits LLM/Apify et subissent le cold-start Render. À ajouter dans un projet Playwright
séparé `@expensive` lancé manuellement si besoin.
