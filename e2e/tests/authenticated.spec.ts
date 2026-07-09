import { test, expect } from "@playwright/test";
import { gotoTab, gotoSubTab } from "./helpers";

// Parcours authentifiés en LECTURE SEULE (pas de génération → aucun coût LLM/Apify).
test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("onglet Veille : sous-onglets Analyser / Mes influenceurs (Dashboard fusionné)", async ({ page }) => {
  await gotoTab(page, "Veille");
  // Deux sous-onglets depuis la fusion ALE-132 (le Dashboard n'est plus un onglet dédié).
  await expect(page.locator(".tab", { hasText: "Analyser" })).toBeVisible();
  await expect(page.locator(".tab", { hasText: "Mes influenceurs" })).toBeVisible();
  await expect(page.locator(".tab", { hasText: "Dashboard" })).toHaveCount(0);
  // Sous-onglet par défaut : la zone de soumission de série.
  await expect(page.getByRole("heading", { name: /Analyser des profils/i })).toBeVisible();
  // Bascule vers « Mes influenceurs » : bloc « Tendances de ta veille » + classement épuré
  // (l'ancien Dashboard global à 3 tableaux a été remplacé par cette vue).
  await page.locator(".tab", { hasText: "Mes influenceurs" }).click();
  await expect(page.getByRole("heading", { name: /^Mes influenceurs$/i })).toBeVisible();
  await expect(page.getByText(/Tendances de ta veille/i).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: /Dashboard global/i })).toHaveCount(0);
  // ALE-214 : si des influenceurs sont listés, la colonne de veille (suivi) est présente.
  const influencersTable = page.locator("table.dash-table").first();
  if (await influencersTable.count()) {
    await expect(influencersTable.locator("th", { hasText: "Veille" })).toBeVisible();
    await expect(influencersTable.locator("th", { hasText: "Rapport" })).toBeVisible();
  }
  await expect(page.locator(".error")).toHaveCount(0);
});

test("Contenu › Ma bibliothèque : onglet fusionné à tiroirs (ALE-223)", async ({ page }) => {
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Ma bibliothèque");
  // ALE-223 : le sous-onglet « Mes contenus » a été fusionné ici → il n'existe plus.
  await expect(page.locator(".tab", { hasText: "Mes contenus" })).toHaveCount(0);
  // Tiroir 1 (ouvert par défaut) : les contenus sauvegardés.
  await expect(page.getByRole("heading", { name: /Mes contenus sauvegardés/i })).toBeVisible();
  // Tiroir « Posts de référence & templates » : replié par défaut → le champ d'ajout
  // par lien est masqué tant qu'on n'a pas ouvert le tiroir.
  const libToggle = page.getByRole("button", { name: /Posts de référence & templates/i });
  await expect(libToggle).toBeVisible();
  await expect(page.getByPlaceholder(/Colle le lien du post LinkedIn/i)).toHaveCount(0);
  await libToggle.click();
  await expect(page.getByPlaceholder(/Colle le lien du post LinkedIn/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /Ajouter à ma bibliothèque/i })).toBeVisible();
  // Le tiroir interne « Plus d'options » expose texte collé, note, structure à la main.
  await page.getByText(/Plus d'options/i).click();
  await expect(page.getByPlaceholder(/colle le texte du post directement/i)).toBeVisible();
  await expect(page.getByPlaceholder(/Nom de la structure/i)).toBeVisible();
  await expect(page.locator(".error")).toHaveCount(0);
});

test("Veille › Monitoring d'influenceurs : fil de veille rendu sans erreur (ALE-215)", async ({ page }) => {
  await gotoTab(page, "Veille");
  await page.locator(".tab", { hasText: "Monitoring d'influenceurs" }).click();
  await expect(page.getByRole("heading", { name: /^Monitoring d'influenceurs$/i })).toBeVisible();
  // Bouton de rafraîchissement toujours présent ; l'état vide invite à suivre des influenceurs.
  await expect(page.getByRole("button", { name: /Rafraîchir/i })).toBeVisible();
  await expect(page.locator(".error")).toHaveCount(0);
});

test("onglet Mon profil : contexte éditorial direct (plus de sous-onglet Tableau de bord, ALE-224)", async ({ page }) => {
  await gotoTab(page, "Mon profil");
  // ALE-224 : le sous-onglet « Tableau de bord » a été retiré → le contexte éditorial
  // s'affiche directement, sans onglet intermédiaire.
  await expect(page.getByRole("heading", { name: /Contexte éditorial/i })).toBeVisible();
  await expect(page.locator(".tab", { hasText: "Tableau de bord" })).toHaveCount(0);
  // Le bouton de sauvegarde manuelle reste présent…
  await expect(page.getByRole("button", { name: /Sauvegarder/i })).toBeVisible();
  // …et la barre de pré-remplissage IA (qui auto-sauve désormais) aussi.
  // Timeout généreux : ce bloc n'apparaît qu'une fois `/me/profile` chargé, et
  // le backend dev free-tier peut mettre 30-50 s au 1er appel (cold-start).
  await expect(page.getByPlaceholder(/Description, URL LinkedIn ou site web/i)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("button", { name: /Pré-remplir/i })).toBeVisible();
});

test("onglet Mon profil : 2ᵉ switch « idée du jour » présent et synchronisé (ALE-224)", async ({ page }) => {
  await gotoTab(page, "Mon profil");
  // Le switch d'opt-in « idée du jour » est aussi accessible depuis le profil
  // (en plus de Contenu › Idée du jour), sans bandeau d'erreur.
  await expect(page.getByText(/Recevoir une idée chaque matin/i)).toBeVisible();
  await expect(page.locator(".error")).toHaveCount(0);
});

test("onglet Mon profil : encart de publication X (Twitter) rendu", async ({ page }) => {
  await gotoTab(page, "Mon profil");
  // L'encart de cross-post X est présent (entre LinkedIn et Slack).
  await expect(page.getByText(/Publier sur X \(Twitter\)/i)).toBeVisible();
  // Selon l'état de connexion du compte de test : soit le bouton « Connecter X »,
  // soit le pill « Connecté ». L'un des deux doit être visible, sans bandeau d'erreur.
  const connectBtn = page.getByRole("button", { name: /Connecter X/i });
  const connectedPill = page.locator(".status-pill.ok", { hasText: /Connecté/i });
  await expect(connectBtn.or(connectedPill).first()).toBeVisible();
});

// ALE-223 : le sous-onglet « Mes contenus » a été fusionné dans « Ma bibliothèque »
// (tiroir « Mes contenus sauvegardés ») — couvert par le test « onglet fusionné à tiroirs ».

test("Contenu › Générateur de posts : formulaires rendus", async ({ page }) => {
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Générateur de posts");
  // Sections idées + posts fusionnées en un seul bloc « Générer des idées de posts » (idée = post).
  await expect(page.getByRole("heading", { name: /Générer des idées de posts/i })).toBeVisible();
  await expect(page.getByPlaceholder(/Sujet du post/i)).toBeVisible();
  // ALE-222 : le menu Template est toujours visible pour un compte connecté
  // (texte d'aide si la bibliothèque est vide).
  await expect(page.getByText(/Template :/)).toBeVisible();
});

test("onglet Agent IA : interface chat rendue", async ({ page }) => {
  await gotoTab(page, "Agent IA");
  // L'onglet doit devenir actif sans rediriger vers l'auth (donc session OK).
  await expect(page.locator(".nav-item.active", { hasText: "Agent IA" })).toBeVisible();
});

test("Contenu › Idée du jour : idée + réservoir sans erreur", async ({ page }) => {
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Idée du jour");
  await expect(page.getByRole("heading", { name: /^Idée du jour$/i })).toBeVisible();
  // Le réservoir est rendu.
  await expect(page.getByRole("heading", { name: /Mon réservoir d'idées/i })).toBeVisible();
  await expect(page.getByPlaceholder(/Une idée de post/i)).toBeVisible();
  // ALE-224 : le switch d'opt-in a été déplacé dans Mon profil → plus ici.
  await expect(page.getByText(/Recevoir une idée chaque matin/i)).toHaveCount(0);
  // Aucun bandeau d'erreur de chargement (daily-ideas + idea-seeds).
  await expect(page.locator(".error")).toHaveCount(0);
});

test("Contenu › Idée du jour : plus de posts de référence ni de note de renvoi (ALE-222/224)", async ({ page }) => {
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Idée du jour");
  // L'ancienne section ALE-67 n'existe plus ici (déménagée dans Ma bibliothèque)…
  await expect(page.getByRole("heading", { name: /Mes posts de référence/i })).toHaveCount(0);
  // …et la note de renvoi temporaire a été retirée (ALE-224).
  await expect(page.getByText(/Tes posts de référence sont désormais dans/i)).toHaveCount(0);
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
