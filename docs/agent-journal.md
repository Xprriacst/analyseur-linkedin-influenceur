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

## 2026-07-06 (ter) — (hors routine) Correction du verrou : fichier-verrou git au lieu de update_trigger
**Déclencheur** : le run de 10h15 (entrée ci-dessous) a parfaitement diagnostiqué que le verrou
« 2026-07-06 (bis) » était INEXÉCUTABLE — `update_trigger`/`list_triggers` ne sont pas exposés à
la session de la routine, donc l'étape A échouait et le run s'arrêtait fail-closed → 0 issue.
Le journal a fait son travail : il a attrapé ma régression.
**Hypothèse corrigée** : je craignais une corruption git par 2 runs dans le même dossier. Or
chaque tir du cron démarre une **session fraîche isolée** (clone neuf, branche à nom aléatoire)
→ pas de dossier partagé, pas de corruption. Seul vrai risque = 2 runs même fenêtre → même issue.
**Fix (prompt mis à jour)** : verrou remplacé par un **fichier-verrou git `docs/.routine-lock`**
sur `dev`, avec TTL 3h, **best-effort** et **fail-SAFE** (si un run plante, le verrou expire seul ;
si le lock échoue, le run continue au lieu de s'arrêter). N'utilise que git (toujours dispo),
plus aucune dépendance à `update_trigger`/`list_triggers`.
**À savoir pour le prochain run** : au démarrage, lis/pose `docs/.routine-lock` comme décrit dans
le prompt (section VERROUILLAGE). Ne rappelle JAMAIS `update_trigger`/`list_triggers` (absents).

## 2026-07-06 10h15 — routine issues Linear (BLOQUÉE au verrouillage — aucune issue traitée)
**Issues traitées** : aucune. Le run s'est arrêté à l'**étape A** (verrouillage anti-chevauchement),
comme le prompt l'exige, avant tout choix d'issue.
**Ce qui a été fait** : rien côté issues/PR. Seule action : cette entrée de journal.
**Difficultés rencontrées (bloquant)** : les outils **`update_trigger` et `list_triggers`
n'existent PAS dans cette session**. Recherche exhaustive via ToolSearch (3 requêtes :
« update trigger enable disable list triggers », « trigger schedule automation Projet Cibl »,
« list_triggers update_trigger enabled cron job remote ») → seuls outils de planification
disponibles : `CronCreate`/`CronList`/`CronDelete` (jobs **session-only en mémoire**, PAS le
trigger persistant « Projet Cibl ») et `ScheduleWakeup` (pacing /loop). Impossible donc de
faire `update_trigger(trigger_id:"trig_01TsJXTZXGkemc485quuEMeN", enabled:false)`.
Le prompt est explicite pour ce cas : « Si cet appel échoue (outil indisponible, erreur) :
N'EXÉCUTE PAS le reste du run. […] Note l'échec dans le rapport final et arrête-toi là. »
→ arrêt volontaire, fail-closed respecté.
**Leçons / à savoir pour le prochain run** :
- **Le verrouillage ajouté le 2026-07-06 (bis) rend la routine INEXÉCUTABLE dans cet
  environnement** : `update_trigger`/`list_triggers` ne sont pas des outils exposés à la
  session (ils ne font partie ni du MCP GitHub, ni de Linear, ni d'aucun connecteur listé).
  Tant que ce n'est pas corrigé, CHAQUE run s'arrêtera à l'étape A → 0 issue traitée, exactement
  le symptôme « la routine ne fait rien » qu'on cherchait à résoudre.
- **Décision à prendre par Alex** (au choix) : (a) fournir/brancher le vrai outil de gestion
  du trigger (le connecteur qui expose `update_trigger`/`list_triggers`) ; OU (b) rendre le
  verrou **best-effort** dans le prompt — tenter `update_trigger`, mais si l'outil est absent,
  **continuer quand même** (le risque de chevauchement réel dépend de si un 2ᵉ run peut
  vraiment démarrer dans le même environnement pendant qu'un 1er tourne — à confirmer) ; OU
  (c) remplacer l'anti-chevauchement par un autre mécanisme (ex. lockfile commité, ou fenêtre
  cron plus large). Je n'ai PAS modifié le prompt de moi-même : c'est un arbitrage produit.
- Rien n'a été laissé en suspens côté git/PR/Linear (aucune branche créée, aucune PR ouverte).
  Le trigger « Projet Cibl » n'a **pas** été désactivé (impossible), il reste donc **actif** —
  contrairement au scénario « fail-closed » décrit dans l'entrée précédente. Pas de risque de
  trigger resté OFF ici.

## 2026-07-06 (bis) — (hors routine) Verrouillage anti-chevauchement des runs
**Contexte** : le trigger « Projet Cibl » (`trig_01TsJXTZXGkemc485quuEMeN`) est un **cron horaire**
(`0 * * * *`), mais une boucle complète (jusqu'à 6 issues, chacune avec une attente CI de
~20 min max) peut dépasser 1-2h → un run pouvait encore tourner quand l'heure suivante
sonnait, avec risque de course (deux runs concurrents dans le même environnement : checkout/
commit/push simultanés = état git corrompu possible, ou doublon si les deux runs choisissent
la même issue avant que l'un ait poussé).
**Fix** : le prompt (`docs/routine-agent-issues.prompt.md`) s'auto-verrouille désormais —
`update_trigger(enabled:false)` en toute première action, `update_trigger(enabled:true)` en
toute dernière action (même après échec). Si le run plante avant de se réactiver, le trigger
reste désactivé (fail-closed, volontaire).
**À savoir pour le prochain run** : si tu découvres que le trigger « Projet Cibl » est
**désactivé** en démarrant, c'est probablement le signe qu'un run précédent a planté avant
sa réactivation — va lire les dernières entrées de ce journal + les PR ouvertes avant de
demander à Alex de le réactiver, plutôt que de le réactiver silencieusement toi-même.

## 2026-07-06 — (entrée initiale, hors routine) Diagnostic & outillage de l'autonomie
**Contexte** : la routine « traiter les issues Linear » ne créait jamais de PR ni ne lançait les tests.
**Causes identifiées (vérifiées)** :
1. Le prompt reposait sur le CLI `gh`, **absent** des sessions Claude Code distantes → toutes les étapes PR échouaient. Il faut les outils MCP GitHub (`create_pull_request`, `merge_pull_request`, `pull_request_read`, …).
2. Sessions fraîches sans `node_modules` → `npm run build` impossible. Corrigé par le hook SessionStart (`.claude/hooks/session-start.sh`).
3. Allowlist quasi vide → blocages permission en headless. Corrigé dans `.claude/settings.json`.
4. Connecteur Linear parfois non authentifié en session automatique → mises à jour d'issues à traiter en best-effort.
**Outillage posé** : CI `pr-guardrails.yml` exécute désormais `py_compile` + `npm run build` sur chaque PR ; prompt corrigé dans `docs/routine-agent-issues.prompt.md` ; ce journal créé.
**À savoir pour le prochain run** : la branche par défaut du repo est `main` (piège) — brancher depuis `origin/dev`. Le « vert » CI fait foi pour l'auto-merge dans `dev` ; `main` est intouchable (release manuelle par Alex).
