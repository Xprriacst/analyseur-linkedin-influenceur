# Checklist de test manuel (avant release)

À faire **à la main** avant de merger une release importante. Couvre ce que les tests
Playwright automatiques (`e2e/tests/`) **ne couvrent pas** : génération réelle (coût
LLM/Apify), persistance après refresh, publication externe.

- **Où** : `https://lkd-outreach-dev.netlify.app` (dev) — ou prod après merge.
- **Connecté** : ton compte, ou le compte de test `qa.playwright@lkd-outreach.app` / `Lkd!Test2026`.
- ⏳ Le 1er appel backend peut être lent (cold-start Render free-tier ~30-50 s).

> Les sections **1, 2, 3, 6** sont prioritaires (zones modifiées + régressions historiques).
> Les sections **4, 5** sont coûteuses/externes (non automatisées).

## 1. Profil — auto-sauvegarde
- [ ] Onglet **Mon profil** → coller une description (ou URL LinkedIn) dans la barre IA → **« Pré-remplir »**.
- [ ] Les champs se remplissent ; message **« généré… et enregistré »** (pas « relis puis sauvegarde »).
- [ ] **Recharger la page (F5)** → le profil est **toujours là** (bug historique : il disparaissait).
- [ ] Modifier un champ à la main → **Sauvegarder** → F5 → la modif persiste.

## 2. Génération de posts — persistance
- [ ] **Générateur de posts** → un sujet → **Générer** → 3 variants s'affichent.
- [ ] **Mes contenus → Posts** → les 3 posts apparaissent (sujet, rôle, date).
- [ ] F5 → toujours présents.

## 2bis. Génération depuis un PDF source (ALE-187)
- [ ] **Générateur** → **« 📄 Générer depuis un PDF »** → choisir un PDF (< 10 Mo) → une pastille 📄 avec le nom du fichier apparaît.
- [ ] **Générer** (avec ou sans sujet) → les posts s'appuient sur le **contenu réel du document** (idées, chiffres exacts — vérifier contre le PDF).
- [ ] Avec un sujet en plus → le sujet sert d'**angle** pour exploiter le document.
- [ ] Dans **Mes contenus**, les posts générés sans sujet affichent « PDF : nom-du-fichier » comme sujet.
- [ ] PDF > 10 Mo ou fichier non-PDF → refusé avec message clair, aucun crédit débité.
- [ ] « Retirer » la pastille → la génération suivante repart sans document.

## 3. Génération d'idées — persistance
- [ ] **Générateur → Générer des idées** → idées affichées.
- [ ] **Mes contenus → Idées** → présentes après F5.

## 4. Mes contenus — relire & réutiliser
- [ ] **Copier le post** / **Copier l'accroche** → coller ailleurs : texte correct.
- [ ] Idée → **« Générer ce post »** → bascule sur le Générateur, sujet pré-rempli, génération lancée.
- [ ] Post → **« Régénérer sur ce sujet »** → idem.
- [ ] **Supprimer** un post puis une idée → disparaît tout de suite → F5 → toujours supprimé.

## 5. Publication LinkedIn + image (externe)
- [ ] Mon profil → **Connecter LinkedIn** → retour app « Connecté ».
- [ ] Variant → **Publier sur LinkedIn** → modal de confirmation → Confirmer → « Publié ✓ » (vérifier sur LinkedIn).
- [ ] **Enregistrer en brouillon** → « Brouillon ✓ » (vérifier côté Zernio/LinkedIn).
- [ ] **Générer une image** → image affichée + téléchargeable.

## 5bis. Programmation — même modal partout (ALE-184)
- [ ] **Programmer** ouvre la **même fenêtre** (date/heure + « Valider via Slack » + « Programmer sur LinkedIn ») depuis les 4 endroits : Générateur, Mes contenus, Idée du jour, réponse de l'Agent IA.
- [ ] Slack non connecté → bouton « Valider via Slack » grisé (info-bulle « Connecte Slack… »).
- [ ] Slack connecté → « Valider via Slack » → message reçu sur Slack ; le post ne part sur LinkedIn qu'après validation (cron ~5 min après l'heure choisie).
- [ ] « Programmer sur LinkedIn » (direct) → le post part à l'heure choisie sans passer par Slack.
- [ ] Un post de Mes contenus **avec images** programmé → les images sont bien conservées à la publication.

## 6. Isolation / sécurité (régression historique)
- [ ] Connecté en compte A (noter ses contenus) → **déconnexion** → connexion compte B **dans le même onglet**.
- [ ] B ne voit **aucun** contenu/profil/post de A (Mes contenus, Analyses récentes, Profil).
