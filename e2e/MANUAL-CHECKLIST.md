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

## 5ter. Pièce jointe PDF — post « document » LinkedIn (ALE-186)
- [ ] Générateur ou Mes contenus → **« Joindre images / PDF »** → choisir un PDF (< 20 Mo) → il s'affiche comme pièce jointe 📄 (pas d'aperçu image).
- [ ] Joindre un PDF **remplace** les images existantes (et inversement) avec un message explicatif — LinkedIn ne mélange pas les deux.
- [ ] PDF > 20 Mo → refusé avec message clair.
- [ ] **Publier** le post avec PDF → sur LinkedIn, le PDF apparaît en **carrousel feuilletable** (titre = nom du fichier).
- [ ] **Programmer** un post avec PDF (direct et via validation Slack) → le PDF est conservé à la publication ; sur Slack, une ligne « 📄 Document joint » avec lien apparaît sous le post.
- [ ] Post avec PDF **sauvegardé** dans Mes contenus → après F5, la pièce 📄 est toujours là.

## 6. Isolation / sécurité (régression historique)
- [ ] Connecté en compte A (noter ses contenus) → **déconnexion** → connexion compte B **dans le même onglet**.
- [ ] B ne voit **aucun** contenu/profil/post de A (Mes contenus, Analyses récentes, Profil).
