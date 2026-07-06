# Prompt de routine — traitement autonome des issues Linear (version corrigée)

> Version corrigée du 2026-07-06. Changements vs l'ancienne routine :
> - **Plus aucun `gh`** (le CLI n'existe pas dans les sessions distantes → c'était la cause des PR jamais créées). Tout GitHub passe par les **outils MCP GitHub**.
> - Dépendances installées par le **hook SessionStart** (`.claude/hooks/session-start.sh`) → `npm run build` fonctionne.
> - Tests **aussi garantis par la CI** (`pr-guardrails.yml` : py_compile + build) → le merge auto dans `dev` est sûr même si le build local a un souci.
> - **Échecs explicites** : plus jamais de skip silencieux.
> - Linear = **best-effort** (peut être déconnecté en session automatique).

---

Tu travailles sur le projet Linear « 📊 Analyse influenceurs LinkedIn + Génération de posts ».

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

BOUCLE PRINCIPALE — répète tant qu'il reste des issues Backlog/Todo éligibles (max 6) :

1. CHOIX DE L'ISSUE
   - La plus prioritaire parmi Backlog/Todo UNIQUEMENT.
   - Ignore Done / In Review / Cancelled / Duplicate + labels « manque d'info d'Alex » / « à arbitrer ».
   - À priorité égale : d'abord les Bugs, puis la plus petite.
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
