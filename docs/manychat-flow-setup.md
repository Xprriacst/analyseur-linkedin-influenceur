# Configurer le flow ManyChat de l'agent Instagram

Ce guide explique comment relier un compte ManyChat à l'agent de qualification
Instagram de l'app. Une fois en place, chaque DM Instagram reçu est envoyé à
l'agent, qui prépare une réponse (visible dans l'onglet **Inbox**) et, en mode
autopilot vert, répond seul.

> ⚠️ ManyChat ne permet pas de créer un flow par API : ces étapes se font **à la
> main dans l'interface ManyChat**. Comptez ~2 minutes.

## Prérequis

1. Un **compte Instagram professionnel ou créateur**, connecté à ManyChat
   (ManyChat → Settings → Instagram).
2. Un **plan ManyChat Pro** : l'action « External Request » (indispensable ici)
   n'existe que sur Pro (~15 $/mois).
3. Dans l'app, onglet **Inbox → « 🔌 Connecter ManyChat »** : coller la clé API
   ManyChat (ManyChat → Settings → API → *Generate your token*). L'app affiche
   alors **ton URL de webhook personnelle** et **ton secret** — garde-les sous
   la main pour l'étape 2 ci-dessous.

## Étape 1 — Créer l'automatisation « Réponse par défaut »

Dans ManyChat, ouvre **Automation → New Automation** (ou **Default Reply** pour
Instagram, qui se déclenche sur tout DM ne correspondant à aucun mot-clé) :

- **Déclencheur (Trigger)** : Instagram → **Default Reply** (« Réponse par
  défaut »). C'est le filet qui attrape tous les DM entrants.
- Ajoute une étape **Action → External Request**.

## Étape 2 — Configurer l'action « External Request »

Renseigne exactement :

| Champ | Valeur |
|---|---|
| **Method** | `POST` |
| **Request URL** | ton URL de webhook personnelle (copiée depuis l'app) |
| **Headers** | ajoute un en-tête `X-ManyChat-Secret` = ton secret (copié depuis l'app) |
| **Body / Content-Type** | `application/json` |

**Body (JSON)** — clique sur les champs pour insérer les *system fields*
ManyChat (ne tape pas les valeurs à la main) :

```json
{
  "subscriber_id": "{{Contact ID}}",
  "name": "{{Full Name}}",
  "text": "{{Last Text Input}}"
}
```

- `subscriber_id` → insère le champ système **Contact ID** (c'est l'identifiant
  que l'app réutilise pour renvoyer les réponses).
- `name` → **Full Name** (ou First Name + Last Name).
- `text` → **Last Text Input** (le dernier message tapé par le prospect).

Tu n'as **pas besoin** de mapper la réponse de la requête (« Response mapping ») :
l'agent ne répond pas via ce flow, il renvoie ses messages directement par l'API
ManyChat avec ta clé. L'External Request sert uniquement à **transmettre le DM
entrant** à l'agent.

## Étape 3 — Publier et tester

1. **Publie** l'automatisation ManyChat.
2. Depuis un autre compte Instagram, envoie un DM à ton compte.
3. Le message doit apparaître dans l'onglet **Inbox** de l'app, avec la réponse
   suggérée par l'agent. En mode supervisé, tu valides (ou édites) puis envoies ;
   en autopilot vert, l'agent a déjà répondu.

> 💡 Avant de brancher un vrai compte, tu peux valider tout le comportement de
> l'agent avec le **Simulateur** (bouton « 🧪 Simulateur » de l'Inbox) : il
> rejoue le même pipeline sans passer par ManyChat.

## Nouvelle interface ManyChat (« Flow Builder » 2026)

Depuis 2026, l'UI ManyChat a changé et **« Default Reply » n'apparaît plus dans la
liste des triggers**. Voici le parcours équivalent, écran par écran.

1. **Automation → New Automation.**
2. **Trigger** : dans la liste des événements Instagram, choisis **« Instagram
   Message » (« User sends a message »)**. (Les autres — *Post/Reel Comments*,
   *Story Reply*, *Ads*… — ne sont que des déclencheurs partiels.)
3. ManyChat propose alors deux façons de déclencher :
   - **« Detect specific words in a message »** → filtre sur un **mot-clé** : ne
     transmet QUE les DM contenant ce mot. À éviter en production.
   - **« Recognize intention of a message »** → filtre par thème via l'IA ManyChat.
   Pour un vrai **attrape-tout** (tous les DM), utilise plutôt le **Default Reply**
   classique : lien **« Go To Basic Builder »** en haut à droite → il expose la
   **Réponse par défaut** sans mot-clé. (Pour un simple test de branchement, un
   mot-clé bidon comme `test` suffit à valider le webhook.)
4. **Supprime le bloc « Send Message »** créé par défaut : l'agent répond via
   l'API, ManyChat n'a pas à envoyer de message.
5. Ajoute une étape **Actions → + Action → External Request**.
6. Dans la fenêtre **« Edit Request »** :
   - **Request Type** : `POST`.
   - **Request URL** : ton URL de webhook (copiée depuis l'app). Format :
     `https://analyseur-linkedin-influenceur-api.onrender.com/manychat/webhooks/inbound/<ton-token>`
     — le token final est une longue chaîne aléatoire propre à ton compte ; ne
     recopie jamais un exemple, prends la vraie valeur affichée dans l'app.
   - **Contact for testing** : ton prénom (sert au bouton « Test Request »).
   - Onglet **Headers → + Request Header** : `X-ManyChat-Secret` = ton secret.
   - Onglet **Body** : type `JSON`, colle le corps de l'Étape 2 en insérant les
     *system fields* via le bouton `{ }` (**Contact ID**, **Full Name**,
     **Last Text Input**).
   - Onglet **Response mapping** : ne touche à rien.
   - **Test Request** → doit renvoyer **200** (403 = mauvais secret, 404 = mauvaise
     URL / compte délié). Puis **Save**.
7. **Set Live** (en haut à droite) pour publier.

> ⚠️ **Plan** : l'action **External Request** exige un **compte Pro**. En **Trial**,
> tu peux construire le flow mais l'exécution réelle du webhook nécessitera le
> passage en Pro.

## Notes vocales

Bonne nouvelle : **aucun champ supplémentaire à ajouter au body**. Quand un
prospect envoie une note vocale sur Instagram, ManyChat range **l'URL du fichier
audio directement dans le champ « Last Text Input »** (ManyChat n'a pas de champ
dédié pour l'audio entrant). Ton body actuel envoie donc déjà cette URL dans
`text` — le backend la **reconnaît** (URL se terminant par `.ogg`, `.mp3`, …) et
la **transcrit** automatiquement (Speech-to-Text) au lieu de l'afficher brute.

⚠️ **Condition indispensable** : ton automation doit se déclencher sur **tous**
les messages entrants — utilise la **Réponse par défaut (Default Reply) attrape-
tout**, pas un mot-clé. Un vocal ne contient aucun texte : un déclencheur par
mot-clé ne se déclenchera jamais dessus, et le vocal n'arrivera pas au backend.

> ManyChat expose aussi une condition **« Last Reply Type : text/audio »** pour
> router selon le type — connue pour être peu fiable ; inutile ici puisque le
> backend distingue lui-même texte et audio.

## Dépannage

- **403 / « Secret ManyChat invalide »** : le header `X-ManyChat-Secret` ne
  correspond pas au secret affiché dans l'app. Recopie-le exactement.
- **404 / « Webhook ManyChat inconnu »** : l'URL est erronée ou le compte a été
  délié dans l'app. Reconnecte-toi via « 🔌 Connecter ManyChat » et recopie l'URL.
- **Le message n'arrive pas dans l'Inbox** : vérifie que l'automatisation est
  bien **publiée** (**Set Live**) et que le déclencheur attrape bien **tous** les
  DM (Default Reply, ou « Instagram Message » sans mot-clé restrictif — voir la
  section « Nouvelle interface » ci-dessus). Contrôle aussi que le corps envoie
  bien `subscriber_id` et `text`.
- **La réponse ne part pas au prospect** : l'envoi conforme n'est possible que
  dans la **fenêtre de 24 h** après le dernier message du prospect (règle Meta).
