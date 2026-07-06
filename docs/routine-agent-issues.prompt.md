# Prompt de routine — traitement autonome des issues Linear (version corrigée)

> Version corrigée du 2026-07-06. Changements vs l'ancienne routine :
> - **Plus aucun `gh`** (le CLI n'existe pas dans les sessions distantes → c'était la cause des PR jamais créées). Tout GitHub passe par les **outils MCP GitHub**.
> - Dépendances installées par le **hook SessionStart** (`.claude/hooks/session-start.sh`) → `npm run build` fonctionne.
> - Tests **aussi garantis par la CI** (`pr-guardrails.yml` : py_compile + build) → le merge auto dans `dev` est sûr même si le build local a un souci.
> - **Échecs explicites** : plus jamais de skip silencieux.
> - Linear = **best-effort** (peut être déconnecté en session automatique).
> - **Verrouillage anti-chevauchement** : via un **fichier-verrou git** (`docs/.routine-lock`) avec TTL,
>   best-effort. N'utilise que git (les outils de trigger `update_trigger`/`list_triggers` ne sont PAS
>   exposés à la session de la routine — vérifié le 2026-07-06, ne PAS les rappeler).
> - **Sélection pilotée par le label** « à lancer par un agent » (équipe entière, plus un seul projet)
>   + **respect des dépendances `blockedBy`**. Avant, la routine prenait « la plus prioritaire du projet »
>   → elle ignorait le label et faisait des issues sans rapport (ex. ALE-181 le 2026-07-06). Le label est
>   désormais l'interrupteur qu'Alex contrôle.

---

Tu travailles sur l'équipe Linear **Alexclareo**. Tu ne traites QUE les issues portant le label
**« à lancer par un agent »** (le contrat de sélection — détaillé à l'étape 1), quel que soit leur
projet. Ne te limite PAS à un seul projet Linear.

VERROUILLAGE ANTI-CHEVAUCHEMENT (À FAIRE EN TOUT PREMIER — avant toute autre étape, avant
même de lire le journal)
Pourquoi : le trigger cron **« Projet Cibl »** est horaire (`0 * * * *`), mais une boucle
complète (jusqu'à 6 issues, chacune avec ~20 min d'attente CI) peut dépasser 1-2h → un run
peut encore tourner quand l'heure suivante sonne. Chaque tir démarre TRÈS PROBABLEMENT une
**session fraîche isolée** (clone neuf, branche à nom aléatoire) → deux runs ne partagent PAS
le même dossier de travail (donc pas de corruption git concurrente). Le seul vrai risque = deux
runs de la même fenêtre qui choisissent la même issue. On le couvre par un fichier-verrou.

Mécanisme = **fichier-verrou git `docs/.routine-lock` sur `dev`, avec TTL, best-effort.**
N'utilise QUE git (toujours disponible). ⚠️ N'utilise PAS `update_trigger`/`list_triggers` :
ces outils ne sont PAS exposés à cette session (vérifié le 2026-07-06 — les rappeler ne fait
qu'arrêter la routine pour rien).

- **Étape A (avant tout le reste)** :
  1. `git fetch origin dev`, puis lis `docs/.routine-lock` sur `origin/dev` s'il existe
     (il contient une ligne `started_at: <ISO8601 UTC>`).
  2. S'il existe ET que `started_at` a MOINS de 3h (compare à `date -u +%FT%TZ`) : un autre
     run est probablement actif → **arrête-toi proprement**, sans traiter d'issue. Ajoute une
     entrée de journal « run sauté : verrou actif (démarré à <started_at>) ». Pas d'autre action.
  3. Sinon (absent, OU périmé > 3h → run précédent probablement planté) : pose le verrou.
     Sur un `dev` à jour, écris `docs/.routine-lock` avec `started_at: <maintenant ISO UTC>`
     + `run: <horodatage unique>`, commit `routine: lock <date>`, `git push origin dev`.
     - Push REJETÉ (un autre run a poussé entre-temps) → `git pull --rebase origin dev`, relis
       le verrou : s'il est maintenant présent et frais → **arrête-toi** (course perdue) ;
       sinon repose et re-push (max 2 tentatives).
     - Push en échec réseau/autre → retry backoff ; si ça échoue toujours → **CONTINUE quand
       même** le run (best-effort). Mieux vaut un doublon rare qu'une routine qui ne fait jamais
       rien (c'est l'erreur du 2026-07-06). Note-le au journal.
- **Étape Z (toute dernière action du run, succès comme échec)** : retire le verrou
  (`git rm docs/.routine-lock`), commit `routine: unlock <date>`, `git push origin dev`.
  Best-effort : si ça échoue, note-le — le TTL de 3h nettoiera de toute façon.
- **Fail-SAFE (pas fail-closed)** : si un run plante avant l'étape Z, le verrou reste mais
  **expire seul au bout de 3h** → le run suivant repartira. Jamais de blocage permanent.

CONTEXTE ENVIRONNEMENT (à lire d'abord)
- Le CLI `gh` N'EXISTE PAS ici. Toute opération GitHub (PR, checks, merge) passe par les
  outils MCP GitHub : `create_pull_request`, `search_pull_requests`, `list_pull_requests`,
  `pull_request_read`, `update_pull_request`, `merge_pull_request`, `add_issue_comment`.
  Charge-les via ToolSearch si besoin. N'essaie JAMAIS une commande `gh` dans Bash.
- Les dépendances frontend sont installées au démarrage par le hook SessionStart.
  Si `frontend/node_modules` manque quand même : `cd frontend && npm install` d'abord.
- Le connecteur Linear peut être NON AUTHENTIFIÉ dans une session automatique. Si un appel
  Linear échoue : ne bloque pas — consigne le statut dans le corps de la PR et dans le
  rapport final à la place.
- RÈGLE ANTI-SILENCE : si une étape échoue (PR impossible, build rouge, outil absent…),
  tu le DIS explicitement dans le rapport final avec l'erreur exacte. Tu ne sautes jamais
  une étape en silence.

JOURNAL DE BORD (obligatoire — mémoire entre les runs)
- AU DÉBUT du run : lis les 2-3 dernières entrées de `docs/agent-journal.md` (branche `dev`).
  Elles contiennent les pièges découverts par les runs précédents et les états en suspens
  (PR ouvertes, issues Linear pas mises à jour…). Tiens-en compte.
- À LA FIN du run (même si tout a échoué) : ajoute une entrée EN HAUT du journal, au format
  décrit dans le fichier : issues traitées + PR + statuts, ce qui a été fait, difficultés
  rencontrées (avec messages d'erreur exacts), leçons pour le prochain run.
- Publication du journal : commit du SEUL fichier `docs/agent-journal.md` directement sur
  `dev` (`git fetch origin dev && git checkout dev && git pull origin dev`, édite, commit
  `journal: run routine <date>`, `git push origin dev`). C'est le seul cas où tu pousses
  directement sur dev — un fichier de docs, jamais de code. Si le push échoue : pousse la
  même entrée sur une branche `journal/<date>` et signale-le dans le rapport final.

OBJECTIF
Traiter en AUTONOMIE plusieurs issues, mais UNE À LA FOIS (jamais en parallèle), chacune
dans UNE PR minimale ciblant `dev`. Boucle jusqu'à épuisement du lot ou 6 issues traitées.

RÈGLE D'OR PARALLÉLISME (non négociable)
Boucle SÉRIE : issue → branche → PR → (merge ou stop) → rebranche depuis origin/dev à jour
→ issue suivante. Presque tout touche `frontend/app/page.tsx` : deux branches en parallèle
= conflits garantis.

BOUCLE PRINCIPALE — répète tant qu'il reste des issues éligibles (label « à lancer par un agent »,
Backlog/Todo, non bloquées) — max 6 :

1. CHOIX DE L'ISSUE — PILOTÉ PAR LE LABEL « à lancer par un agent » (le contrat)
   - **Périmètre = équipe `Alexclareo` ENTIÈRE**, pas un projet précis. Récupère les candidates
     via `list_issues(team:"Alexclareo", label:"à lancer par un agent", state:"Backlog")` puis
     idem avec `state:"Todo"`. **Ce label est le seul critère d'entrée** : Alex l'appose sur ce
     qu'il veut voir traité en autonome, l'enlève sinon. Ne prends JAMAIS une issue sans ce label,
     même si elle paraît prioritaire (c'est l'erreur du run du 2026-07-06 08h34 : ALE-181, non
     labellée, a été prise parce que la sélection se faisait par priorité de projet — corrigé).
   - Ignore Done / In Review / In Progress / Cancelled / Duplicate + labels « manque d'info
     d'Alex » / « à arbitrer » (ces derniers priment : une issue « à arbitrer » n'est jamais prise
     même si elle a aussi « à lancer par un agent »).
   - **RESPECTE LES DÉPENDANCES** : pour chaque candidate, `get_issue(id, includeRelations:true)`
     et regarde `blockedBy`. Si elle est bloquée par une issue **encore ouverte** (statut ≠ Done
     et ≠ Cancelled) → **NE LA PRENDS PAS ce run** : elle se débloquera quand son bloquant sera
     terminé. (Ex. epic Agent IG : ALE-201 est non bloquée → OK ; ALE-202/203/204/205 sont
     `blockedBy` ALE-201 → à ignorer tant qu'ALE-201 n'est pas Done.)
   - Parmi les candidates **non bloquées** : priorité la plus haute d'abord ; à priorité égale,
     d'abord les Bugs, puis la plus petite ; puis le plus petit numéro d'ALE (ordre stable et
     prévisible).
   - Issue floue / info manquante → passe-la (commente sur Linear si dispo, sinon note-le
     dans le rapport final), ne devine pas.

2. ANTI-DOUBLON (outils MCP, pas gh)
   - `search_pull_requests` avec la requête `repo:Xprriacst/analyseur-linkedin-influenceur ALE-<num>` (state all).
   - `git ls-remote --heads origin | grep -i "ale-<num>"`
   - Si l'un renvoie un résultat → change d'issue, ne recrée rien.

3. ANTI-MÉGA-PR
   - > ~10 fichiers, refonte d'archi ou migration DB structurante → NE TRAITE PAS.
     Commente « à découper » (Linear si dispo, sinon rapport final) et passe à la suivante.

4. BRANCHE (le repo a `main` comme défaut — piège)
   - `git fetch origin dev`
   - `git checkout -B feat/ale-<num>-<slug> origin/dev`   (TOUJOURS origin/dev, jamais main)

5. IMPLÉMENTATION
   - Ne modifie QUE les fichiers nécessaires. Aucun refactor non demandé.
   - Migration Supabase si besoin : prochain numéro libre dans supabase/migrations/
     (vérifie qu'aucune PR ouverte n'utilise le même), idempotente (IF NOT EXISTS).

6. PORTES DE CONTRÔLE (si une échoue → pas de PR, consigne l'échec, issue suivante)
   - Fraîcheur : `git rev-list --count origin/dev..HEAD` petit (1-3). Si > 5 → abort.
   - Scope : `git diff --name-only origin/dev...HEAD` ne liste que le nécessaire.
   - Pas de conflit : `git grep -nE '^(<<<<<<< |>>>>>>> |=======$)'` ne renvoie rien.
   - Build vert : `python3 -m py_compile api.py src/*.py` puis `cd frontend && npm run build`.
     (La CI re-vérifie les deux sur la PR — mais teste localement d'abord.)

7. PUSH + PR (base = dev OBLIGATOIRE, via MCP)
   - `git push -u origin feat/ale-<num>-<slug>` (retry backoff 2s/4s/8s/16s si réseau).
   - `create_pull_request` : base `dev`, head la branche, titre `ALE-<num> — <résumé>`,
     body = résumé + lien issue Linear + « portes de contrôle passées ».
   - Vérifie la base avec `pull_request_read` : si base ≠ dev → `update_pull_request`
     pour corriger, re-vérifie. Ne termine JAMAIS avec base = main.

8. GATING PAR RISQUE — décide du sort de la PR :

   a) COSMÉTIQUE / RÉVERSIBLE (UI, libellé, badge, griser, masquer — AUCUNE logique de
      données, AUCUNE migration) :
      → Attends la CI en interrogeant `pull_request_read` (statut des checks) toutes les
        ~2-3 min, max ~20 min. N'utilise PAS `sleep` en boucle serrée.
      → Tous les checks verts (dont `guardrails`) ET base=dev confirmée :
        `merge_pull_request` (méthode squash), puis supprime la branche.
        Linear (si dispo) : issue « Done » + commentaire (lien PR + « auto-mergé dans dev »).
      → Un check rouge → laisse la PR ouverte, Linear « In Review » (si dispo), consigne
        l'échec, continue.

   b) COMPORTEMENT / DONNÉES / MIGRATION (persistance, état, flux, auth, toute migration,
      base prod/dev partagée) :
      → NE MERGE PAS. PR ouverte, Linear « In Review » (si dispo) + « à valider par Alex ».

   Doute sur la catégorie → (b), on ne merge pas.

9. ITÉRATION SUIVANTE
   - `git fetch origin dev` (récupère le dev à jour si tu viens de merger).
   - Retour en haut de boucle : la prochaine branche part d'origin/dev à jour.

CE QUE TU NE FAIS JAMAIS
- Jamais de PR vers main (release dev → main = Alex, manuellement). Tu ne touches jamais main.
- Jamais deux issues en parallèle. Jamais plusieurs ALE dans une PR.
- Jamais merger une PR de catégorie (b) ou dont la CI n'est pas verte.
- Jamais utiliser `gh` (n'existe pas). Jamais skipper une étape en silence.

RAPPORT FINAL (obligatoire, même si tout a échoué)
Pour chaque issue : numéro → PR (lien) → statut (auto-mergé dans dev / en attente de
validation Alex / sautée + RAISON PRÉCISE avec l'erreur exacte le cas échéant).
Si Linear était indisponible, liste les mises à jour d'issues restées à faire.
Le même contenu DOIT être ajouté en entrée du journal `docs/agent-journal.md` (voir
« JOURNAL DE BORD » ci-dessus) — le rapport de chat disparaît avec la session, le journal
reste dans le repo.
