import { test, expect } from "@playwright/test";
import { gotoTab, gotoSubTab } from "./helpers";

// Parcours authentifiés en LECTURE SEULE (pas de génération → aucun coût LLM/Apify).
test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("Contenu › Analyses : page empilée (Veille fusionnée, ALE-257)", async ({ page }) => {
  // ALE-257 : la Veille est devenue le sous-onglet « Analyses » de Contenu, en une
  // seule page qui défile (plus d'onglet « Veille » dans la sidebar).
  await gotoTab(page, "Contenu");
  await expect(page.locator(".nav-item", { hasText: "Veille" })).toHaveCount(0);
  await gotoSubTab(page, "Analyses");
  // 1. Bloc de lancement de série (en haut).
  await expect(page.getByRole("heading", { name: /Analyser des profils/i })).toBeVisible();
  // 2. Tiroir « Séries en cours & historique » (replié par défaut) présent.
  await expect(page.getByRole("button", { name: /Séries en cours & historique/i })).toBeVisible();
  // 3. Classement « Mes influenceurs » sur la même page.
  await expect(page.getByRole("heading", { name: /^Mes influenceurs$/i })).toBeVisible();
  // 4. Bloc « Tendances de ta veille » SOUS le classement (ordre voulu ALE-257).
  await expect(page.getByText(/Tendances de ta veille/i).first()).toBeVisible({ timeout: 30_000 });
  // ALE-214 : si des influenceurs sont listés, la colonne de veille (suivi) est présente.
  const influencersTable = page.locator("table.dash-table").first();
  if (await influencersTable.count()) {
    await expect(influencersTable.locator("th", { hasText: "Veille" })).toBeVisible();
    await expect(influencersTable.locator("th", { hasText: "Rapport" })).toBeVisible();
  }
  await expect(page.locator(".error")).toHaveCount(0);
});

test("Contenu › Ma bibliothèque : barre d'ajout en haut + sections en galerie", async ({ page }) => {
  // Refonte : la barre d'ajout est un bandeau en surbrillance toujours visible en
  // haut de page, et chaque section est une galerie (plus de tiroirs à déplier).
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Ma bibliothèque");
  // ALE-223 : le sous-onglet « Mes contenus » a été fusionné ici → il n'existe plus.
  await expect(page.locator(".tab", { hasText: "Mes contenus" })).toHaveCount(0);
  // Barre d'ajout en surbrillance : titre, champ lien et bouton visibles d'emblée.
  const hero = page.locator(".lib-hero");
  await expect(hero.getByRole("heading", { name: /Ajouter à ma bibliothèque/i })).toBeVisible();
  await expect(hero.getByPlaceholder(/linkedin\.com\/posts/i)).toBeVisible();
  await expect(hero.getByRole("button", { name: /^Ajouter$/i })).toBeVisible();
  // Sections rendues en galerie (titres visibles sans rien déplier).
  await expect(page.getByRole("heading", { name: /Posts de référence & templates/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Mes contenus sauvegardés/i })).toBeVisible();
  // « Plus d'options » expose texte collé, note, structure à la main.
  await page.getByText(/Plus d'options/i).click();
  await expect(page.getByPlaceholder(/colle le texte du post directement/i)).toBeVisible();
  await expect(page.getByPlaceholder(/Nom de la structure/i)).toBeVisible();
  await expect(page.locator(".error")).toHaveCount(0);
});

test("Contenu › Ma bibliothèque : section veille des influenceurs (ALE-215/257)", async ({ page }) => {
  // La veille des influenceurs suivis est une section en galerie, en bas de
  // Ma bibliothèque — déplacée depuis l'onglet Analyses puis rationalisée.
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Ma bibliothèque");
  await expect(page.getByRole("heading", { name: /Veille des influenceurs suivis/i })).toBeVisible();
  await expect(page.locator(".error")).toHaveCount(0);
});

test("Mon profil : contexte éditorial sur son propre onglet, champs visibles d'emblée", async ({ page }) => {
  await gotoTab(page, "Mon profil");
  // La page est désormais découpée en 3 onglets (contexte / comptes reliés /
  // ce qui tourne tout seul) au lieu d'empiler les trois sur une même colonne.
  await expect(page.locator(".tab", { hasText: "Mon profil" })).toBeVisible();
  await expect(page.locator(".tab", { hasText: "Connexions" })).toBeVisible();
  await expect(page.locator(".tab", { hasText: "Automatisations" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Contexte éditorial/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Sauvegarder/i })).toBeVisible();
  // Timeout généreux : ce bloc n'apparaît qu'une fois `/me/profile` chargé, et
  // le backend dev free-tier peut mettre 30-50 s au 1er appel (cold-start).
  await expect(page.getByPlaceholder(/Description, URL LinkedIn ou site web/i)).toBeVisible({ timeout: 60_000 });
  // Le tiroir « Détails du profil éditorial » a disparu : les champs ne se méritent
  // plus d'un clic, l'onglet leur est dédié.
  await expect(page.getByLabel("Nom public")).toBeVisible();
  await expect(page.getByText(/Détails du profil éditorial/i)).toHaveCount(0);
});

test("Mon profil › Connexions : les 5 comptes en lignes, réglages repliés", async ({ page }) => {
  await gotoTab(page, "Mon profil");
  await page.locator(".tab", { hasText: "Connexions" }).click();

  // Scopé à la zone principale : « LinkedIn » est aussi le nom du réseau dans la
  // barre latérale, et « Slack » celui d'un bouton ailleurs.
  const main = page.getByRole("main");
  for (const name of ["LinkedIn", "Prospection LinkedIn", "Slack", "X (Twitter)", "Instagram (ManyChat)"]) {
    await expect(main.getByText(name, { exact: true })).toBeVisible({ timeout: 60_000 });
  }
  // Ce qui faisait la densité (clé ManyChat, plafonds d'envoi…) ne doit PAS être
  // rendu tant qu'on n'a pas ouvert la ligne concernée.
  await expect(page.getByPlaceholder(/Clé API ManyChat/i)).toHaveCount(0);

  // …et doit apparaître au clic sur la ligne.
  await page.locator("[role=button][aria-expanded]").filter({ hasText: "Instagram (ManyChat)" }).click();
  await expect(page.getByPlaceholder(/Clé API ManyChat/i)).toBeVisible();
  await expect(page.locator(".error")).toHaveCount(0);
});

test("Mon profil › Automatisations : les 3 choses qui tournent sans toi", async ({ page }) => {
  await gotoTab(page, "Mon profil");
  await page.locator(".tab", { hasText: "Automatisations" }).click();

  await expect(page.getByText(/Une idée de post chaque matin/i)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Les posts de ta semaine/i)).toBeVisible();
  await expect(page.getByText(/Réponses aux messages Instagram/i)).toBeVisible();

  // La FAQ de l'agent (gros champ de texte, ex-carte pleine page) n'est chargée
  // et rendue qu'une fois sa ligne dépliée.
  await expect(page.locator("textarea")).toHaveCount(0);
  await page.locator("[role=button][aria-expanded]").filter({ hasText: "Réponses aux messages Instagram" }).click();
  await expect(page.locator("textarea")).toBeVisible();
  await expect(page.locator(".error")).toHaveCount(0);
});

test("l'abonnement a rejoint le solde de crédits, dans la barre latérale", async ({ page }) => {
  await gotoTab(page, "Mon profil");
  // La carte « Abonnement » a quitté le profil (ce n'est pas un réglage) : elle vit
  // sous le solde, là où on vient regarder ce qu'il reste. On ne clique pas :
  // ça ouvrirait une page de paiement Stripe.
  await expect(page.getByText(/^Abonnement$/)).toHaveCount(0);

  const subscribeBtn = page.getByRole("button", { name: /S'abonner/i });
  const manageBtn = page.getByRole("button", { name: /Abonnement .*· Gérer/i });
  // Sur un environnement sans clés Stripe, la facturation est désactivée et rien
  // ne s'affiche — les trois cas sont légitimes.
  const billingHidden = (await subscribeBtn.count()) === 0 && (await manageBtn.count()) === 0;
  if (!billingHidden) {
    await expect(subscribeBtn.or(manageBtn).first()).toBeVisible();
  }
  await expect(page.locator(".error")).toHaveCount(0);
});

// ALE-223 : le sous-onglet « Mes contenus » a été fusionné dans « Ma bibliothèque »
// (tiroir « Mes contenus sauvegardés ») — couvert par le test « onglet fusionné à tiroirs ».

test("Contenu › Générateur de posts : bouton unique + file d'attente (ALE-286)", async ({ page }) => {
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Générateur de posts");
  // ALE-286 : l'ancien formulaire (sujet + rôle + template + nb de variants) est
  // passé dans le parcours guidé — la page ne porte plus qu'un bouton et la file.
  await expect(page.getByRole("button", { name: /Générer un post/i })).toBeVisible();
  await expect(page.getByPlaceholder(/Sujet du post/i)).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /Mes posts/i })).toBeVisible();
  await expect(page.locator(".error")).toHaveCount(0);
});

test("Contenu › Générateur : le parcours propose les 3 points de départ (ALE-286)", async ({ page }) => {
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Générateur de posts");
  await page.getByRole("button", { name: /Générer un post/i }).click();
  // LECTURE SEULE : on ouvre la pop-up et on vérifie les 3 portes d'entrée, sans
  // cliquer « Je n'ai pas d'idée » (qui déclencherait une génération payante).
  const modal = page.getByRole("dialog", { name: /Générer un post/i });
  await expect(modal.getByRole("heading", { name: /Par où on commence/i })).toBeVisible();
  await expect(modal.getByRole("button", { name: /J'ai une idée/i })).toBeVisible();
  await expect(modal.getByRole("button", { name: /Je n'ai pas d'idée/i })).toBeVisible();
  await expect(modal.getByRole("button", { name: /J'ai une inspiration/i })).toBeVisible();

  // « J'ai une idée » : le champ + le réservoir (déplacé ici depuis l'onglet
  // « Idée du jour », retiré côté agence) + les deux issues.
  await modal.getByRole("button", { name: /J'ai une idée/i }).click();
  await expect(modal.getByLabel(/De quoi veux-tu parler/i)).toBeVisible();
  await expect(modal.getByRole("button", { name: /Enregistrer pour plus tard/i })).toBeVisible();
  await expect(modal.getByRole("button", { name: /Continuer/i })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(modal).toHaveCount(0);
});

test("onglet Agent IA : interface chat rendue", async ({ page }) => {
  await gotoTab(page, "Agent IA");
  // L'onglet doit devenir actif sans rediriger vers l'auth (donc session OK).
  await expect(page.locator(".nav-item.active", { hasText: "Agent IA" })).toBeVisible();
});

test("Contenu : le sous-onglet « Idée du jour » a disparu de la vue agence (ALE-286)", async ({ page }) => {
  await gotoTab(page, "Contenu");
  // Il ne subsiste que dans la vue client (compte `ideas_only`), qui n'a pas de
  // sous-onglets du tout — le compte de test, lui, est un compte agence.
  await expect(page.locator(".tab", { hasText: /^Idée du jour$/ })).toHaveCount(0);
  await expect(page.locator(".tab", { hasText: /Générateur de posts/ })).toBeVisible();
  await expect(page.locator(".error")).toHaveCount(0);
});

test("LinkedIn › Prospection : liste des leads + panneau de détail (ALE-229)", async ({ page }) => {
  await gotoTab(page, "Prospection");
  await expect(page.getByRole("heading", { name: /^Prospection$/i })).toBeVisible();
  // Liste de leads OU état vide qui renvoie vers la Veille / Ma bibliothèque.
  await expect(page.getByText(/Aucun lead pour l'instant|lead\(s\)/i).first()).toBeVisible({ timeout: 60_000 });
  // ALE-228 : panneau de ciblage ICP (toujours présent, pré-rempli depuis le profil).
  // Lecture seule : on déplie/replie sans enregistrer (aucune écriture, aucun coût).
  await expect(page.getByText(/Mon ciblage/i)).toBeVisible();
  await page.getByText(/Mon ciblage/i).click();
  await expect(page.getByText(/Ton client idéal/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /Enregistrer & recalculer/i })).toBeVisible();
  await page.getByText(/Mon ciblage/i).click(); // replie
  // Si des leads existent (le compte QA en a via les tests ALE-227) : panneau de détail au clic.
  const firstLead = page.locator("main button.card").first();
  if (await firstLead.count()) {
    await firstLead.click();
    await expect(page.getByText(/Signaux d'intention/i)).toBeVisible();
    await expect(page.getByRole("link", { name: /Voir le profil LinkedIn/i })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByText(/Signaux d'intention/i)).toHaveCount(0);
  }
  await expect(page.locator(".error")).toHaveCount(0);
  // Jumeau grisé « Bientôt » sous Instagram (maquette ALE-226).
  await page.locator(".nav-item", { hasText: "Instagram" }).first().click();
  await expect(page.locator(".nav-item", { hasText: "Bientôt" })).toBeVisible();
});
