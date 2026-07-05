# Epic — Agent de pré-qualification des prospects Instagram

> Statut : proposition d'architecture / découpage (discussion). Rien n'est implémenté.
> Prêt à devenir un **Project Linear** (équipe **ALE**) + issues ci-dessous (à pousser quand le connecteur Linear est réautorisé).

## Vision

Un **agent conversationnel** ("Lia") qui pré-qualifie les prospects arrivant en DM Instagram :
1. **Mode supervisé (copilote)** — l'agent propose une réponse, Alex valide / édite / refuse avant envoi.
2. **Mode autopilot conditionnel** — l'agent répond seul **uniquement quand il sait**, sinon il escalade.
3. **Garde-fou** — confiance faible ou hors périmètre : **aucune réponse auto**, une **alerte** (Slack + in-app).
4. **Sandbox / banc d'essai** — *pas en v1* : le mode supervisé fait déjà office de sandbox (voir Post-MVP).

Module produit **distinct** de l'analyseur LinkedIn, mais réutilise l'infra existante : Anthropic (`src/llm.py`),
Supabase + RLS, le **patron de validation supervisée Slack** (`src/slack.py`, déjà en place : propose → boutons ✅/❌/✏️),
la file de jobs (`src/jobs.py`).

## Décisions actées (2026-07-04)

- **Connectivité DM = middleware, pour aller vite.** Choix : **ManyChat** (voir ci-dessous). On écarte l'API Meta officielle
  au départ (app-review = semaines) et toute automation non officielle (risque de ban).
- **MVP = FAQ + un objectif de conversation, la FAQ écrite à côté** (Google Doc / Notion / fichier), **pas dans l'appli**.
- **Pas de RAG au MVP.** La FAQ (quelques dizaines de Q/R) tient dans le prompt → **prompt-stuffing**. Cohérent avec la
  « Règle d'or » du projet (tant que ça tient dans le prompt, le prompt suffit). Le RAG ne revient que **si** la FAQ dépasse
  ~quelques centaines d'entrées, ou si on veut fouiller par le sens tout l'historique de conversations.
- **Vocaux gérés** — les prospects IG envoient souvent des **notes vocales**. ManyChat expose l'audio entrant via le champ
  « Last Text Input » → action « External Request » qui passe **l'URL du fichier audio** au backend. On transcrit via
  **OpenAI Whisper** (`OPENAI_API_KEY` déjà présent, FR OK, ~0,006 $/min) → texte → même pipeline. Claude n'ingère pas
  l'audio nativement, donc l'étape STT est **obligatoire** quel que soit le middleware. (Limite ManyChat = envoi de vocaux
  *sortants* IG, non nécessaire : l'agent répond en texte.)
- **Détection « elle sait / elle ne sait pas » en v1** — pas une 2ᵉ IA : **même appel Claude**, sortie structurée
  `{ réponse, confiance, besoin_humain, raison }`. « Sait » = **couvert par la FAQ/objectif** (jugement de couverture, fiable),
  pas « connaît le fait » (mal jugé par un LLM). Consigne : si la réponse n'est pas ancrée dans la FAQ → `besoin_humain=true`.
- **Autopilot en v1** — petite couche au-dessus du garde-fou : vert → envoie direct (au lieu de suggérer) ; rouge → escalade + alerte.
  Seuil conservateur, **kill-switch** global « tout en supervisé », autopilot d'abord sur le vert « couvert par la FAQ ».
- **UI des réponses suggérées = inbox/chatbot in-app** (réutilise l'onglet Assistant, `page.tsx`, chat streamé + markdown).
  Une qualif est multi-tours → mieux qu'un fil Slack. **Slack = canal d'alerte optionnel** (ping « nouveau DM » / « l'agent ne sait pas ») ;
  le travail (valider/éditer/envoyer, toggle supervisé↔autopilot) se fait in-app.

---

## Choix du middleware : ManyChat

| Critère | ManyChat (retenu) | Chatfuel (alternative) |
|---|---|---|
| Partenaire Meta officiel | ✅ | ✅ |
| DM Instagram | ✅ | ✅ |
| Appel backend externe (garder Claude comme cerveau) | ✅ action « External Request » + webhooks | ✅ |
| Inbox Live Chat + pause auto par conversation (→ supervisé/autopilot) | ✅ | partiel |
| Prix d'entrée IA | ~29 $/mois (Pro) | comparable |
| Doc / templates / communauté | ✅ (le mieux fourni) | correct |

Contraintes API communes (voie conforme) : **fenêtre de réponse 24 h**, **~200 msg/h/compte**, déclenchement initié par le prospect.

**Deux niveaux d'usage** (commencer simple) :
- **Niveau 0 (zéro code)** : IA native ManyChat entraînée sur la FAQ, Alex répond depuis l'inbox tant qu'il n'a pas confiance. Teste la demande en quelques heures.
- **Niveau 1 (vrai produit)** : ManyChat = tuyau (DM → webhook → **notre backend** → Claude avec la FAQ → réponse). Le mode supervisé (validation Slack) et le garde-fou vivent **dans notre code**.

Sources recherche (juillet 2026) : developers.facebook.com (policy Messenger/IG), manychat.com/pricing, creatorflow.so, setsmart.io, keyapi.ai.

---

## MVP retaillé (périmètre minimal)

> DM entrant → Claude avec **{FAQ collée + objectif}** → sortie `{réponse, confiance, besoin_humain}` →
> **supervisé** : suggestion affichée dans l'inbox in-app → valider/éditer/envoyer ; **autopilot** : si vert, envoi direct.
> Si `besoin_humain` (elle ne sait pas) → **escalade/alerte** (badge in-app + ping Slack), jamais d'envoi auto.

Élimine du MVP : tables base de connaissance, RAG/pgvector, sandbox, app-review Meta.

### ALE-XXX · [MVP] Transcription des vocaux (Speech-to-Text)
- Audio entrant (URL fournie par ManyChat via External Request) → **OpenAI Whisper** → texte → injecté dans le pipeline Claude comme un DM texte.
- Réutilise `OPENAI_API_KEY` (déjà sur Render). Coût ~0,006 $/min, négligeable.
**DoD** : un DM vocal est transcrit puis traité exactement comme un DM texte.

### ALE-XXX · [MVP] Brancher ManyChat ↔ backend (transport)
- Compte IG Business + ManyChat Pro configurés.
- Webhook DM entrant ManyChat → nouvel endpoint backend ; envoi sortant via l'API ManyChat/Meta.
- Respect fenêtre 24 h + quota ~200 msg/h.
**DoD** : un DM réel arrive au backend et une réponse peut repartir vers le prospect.

### ALE-XXX · [MVP] Génération de réponse Claude ancrée FAQ + objectif
- Nouveau prompt de qualification dans `src/llm.py` : injecte la **FAQ (fichier externe)** + **l'objectif** + consigne « si tu ne sais pas, tu passes la main ».
- Sortie structurée : `{ reponse, confiance: 0..1, besoin_humain: bool, raison }`.
**DoD** : sur un jeu de messages test, réponses cohérentes ; messages hors sujet → `besoin_humain=true`.

### ALE-XXX · [MVP] Inbox in-app (chatbot) — réponses suggérées + supervisé
- Inbox in-app : liste des conversations + fil du prospect ; la réponse suggérée s'affiche **dans le chat**.
- Actions : valider / éditer / envoyer ; toggle **supervisé ↔ autopilot** par conversation.
- Réutilise l'onglet Assistant (`page.tsx`, chat streamé + markdown) comme base d'UI.
- Persistance conversations/messages/décisions (Supabase, RLS `auth.uid()=user_id`) — tables légères.
**DoD** : bout-en-bout supervisé sur une vraie conversation depuis l'inbox, zéro envoi sans validation.

### ALE-XXX · [MVP] Garde-fou + autopilot conditionnel
- Garde-fou : `besoin_humain` ou `confiance < seuil` → **aucun envoi auto** → **alerte** (badge in-app + ping Slack optionnel).
- Autopilot : quand activé et garde-fou **vert**, envoi direct ; sinon retombe en supervisé + alerte.
- Seuil conservateur, **kill-switch** global « tout en supervisé », respect fenêtre 24 h + quota ~200 msg/h.
**DoD** : messages hors FAQ 100 % escaladés ; autopilot n'envoie que sur le vert ; kill-switch testé.

---

## Post-MVP (à activer si besoin)

### ALE-XXX · Base de connaissance dans l'appli + RAG *(seulement si la FAQ grossit)*
Sortir la FAQ du fichier externe vers des tables Supabase alimentées par les validations ; activer **pgvector** + embeddings
et recherche sémantique **uniquement** quand la FAQ ne tient plus proprement dans le prompt (~centaines d'entrées) ou qu'on
veut fouiller l'historique par le sens. C'est le premier vrai cas d'usage RAG du projet — **pas avant**.

### ALE-XXX · Sandbox / banc d'essai (eval harness) *(pas en v1)*
Redondant avec le mode supervisé au début : en supervisé, chaque suggestion validée/éditée/refusée est déjà un test
grandeur nature sans risque. La sandbox n'a de valeur que plus tard, pour le **rejeu hors-ligne de non-régression**
(« j'ai changé le prompt/la FAQ → je repasse N conversations passées pour vérifier que rien n'a cassé »), quand on
itère sur du volume.

---

## Notes transverses
- **Coûts** : ManyChat ~29 $/mois + 1 appel Anthropic par réponse. Surveiller la RAM Render (incident OOM 25/06 → Standard 2 GiB) si le volume de DM monte.
- **Conformité** : ne jamais envoyer sans garde-fou vert en autopilot ; respecter la fenêtre 24 h Meta ; conserver l'historique des décisions.
- **Réutilisation maximale** : Slack (validation), `llm.py` (génération), Supabase RLS (multi-user), `jobs.py` (tâches de fond).
