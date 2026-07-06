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

## Notes vocales (optionnel)

Si ManyChat expose l'URL du fichier audio d'un message vocal, ajoute au body :

```json
"audio_url": "{{URL du fichier audio}}"
```

L'agent transcrit alors le vocal (Speech-to-Text) et le traite comme un DM texte.
Sans ce champ, seuls les DM texte sont pris en charge.

## Dépannage

- **403 / « Secret ManyChat invalide »** : le header `X-ManyChat-Secret` ne
  correspond pas au secret affiché dans l'app. Recopie-le exactement.
- **404 / « Webhook ManyChat inconnu »** : l'URL est erronée ou le compte a été
  délié dans l'app. Reconnecte-toi via « 🔌 Connecter ManyChat » et recopie l'URL.
- **Le message n'arrive pas dans l'Inbox** : vérifie que l'automatisation est
  bien **publiée** et que le déclencheur est **Default Reply** (pas un mot-clé
  précis). Contrôle aussi que le corps envoie bien `subscriber_id` et `text`.
- **La réponse ne part pas au prospect** : l'envoi conforme n'est possible que
  dans la **fenêtre de 24 h** après le dernier message du prospect (règle Meta).
