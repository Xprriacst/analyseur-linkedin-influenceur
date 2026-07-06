# Journal de bord des routines agent

> Rempli automatiquement par les routines autonomes (traitement d'issues Linear, etc.),
> **entrée la plus récente en haut**. Chaque run DOIT ajouter une entrée, même (surtout) si
> tout a échoué. Les agents DOIVENT lire les 2-3 dernières entrées au début d'un run pour
> ne pas répéter les mêmes erreurs. Les humains y trouvent l'historique de ce que les
> routines ont réellement fait.

## Format d'une entrée (à copier)

```markdown
## AAAA-MM-JJ HHhMM — <nom de la routine>
**Issues traitées** : ALE-X (PR #N, auto-mergé dev) · ALE-Y (PR #M, In Review) · ALE-Z (sautée)
**Ce qui a été fait** : 1-3 phrases par issue.
**Difficultés rencontrées** : outil manquant, permission refusée, CI rouge, conflit, issue floue…
  avec le message d'erreur EXACT quand il y en a un.
**Leçons / à savoir pour le prochain run** : pièges découverts, états laissés en suspens
  (PR ouvertes à surveiller, issues Linear pas mises à jour car connecteur down, etc.)
```

---

## 2026-07-06 — (entrée initiale, hors routine) Diagnostic & outillage de l'autonomie
**Contexte** : la routine « traiter les issues Linear » ne créait jamais de PR ni ne lançait les tests.
**Causes identifiées (vérifiées)** :
1. Le prompt reposait sur le CLI `gh`, **absent** des sessions Claude Code distantes → toutes les étapes PR échouaient. Il faut les outils MCP GitHub (`create_pull_request`, `merge_pull_request`, `pull_request_read`, …).
2. Sessions fraîches sans `node_modules` → `npm run build` impossible. Corrigé par le hook SessionStart (`.claude/hooks/session-start.sh`).
3. Allowlist quasi vide → blocages permission en headless. Corrigé dans `.claude/settings.json`.
4. Connecteur Linear parfois non authentifié en session automatique → mises à jour d'issues à traiter en best-effort.
**Outillage posé** : CI `pr-guardrails.yml` exécute désormais `py_compile` + `npm run build` sur chaque PR ; prompt corrigé dans `docs/routine-agent-issues.prompt.md` ; ce journal créé.
**À savoir pour le prochain run** : la branche par défaut du repo est `main` (piège) — brancher depuis `origin/dev`. Le « vert » CI fait foi pour l'auto-merge dans `dev` ; `main` est intouchable (release manuelle par Alex).
