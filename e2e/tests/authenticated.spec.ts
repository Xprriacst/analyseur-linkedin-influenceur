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

test("Contenu › Ma bibliothèque : bibliothèque unifiée rendue sans erreur (ALE-222)", async ({ page }) => {
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Ma bibliothèque");
  await expect(page.getByRole("heading", { name: /^Ma bibliothèque$/i })).toBeVisible();
  // Saisie principale : le lien du post (import auto texte + auteur + image + structure).
  await expect(page.getByPlaceholder(/Colle le lien du post LinkedIn/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /Ajouter à ma bibliothèque/i })).toBeVisible();
  // Le tiroir « Plus d'options » expose texte collé, note, structure à la main (ex-ALE-67/216).
  await page.getByText(/Plus d'options/i).click();
  await expect(page.getByPlaceholder(/colle le texte du post directement/i)).toBeVisible();
  await expect(page.getByPlaceholder(/Pourquoi il te plaît/i)).toBeVisible();
  await expect(page.getByPlaceholder(/Nom de la structure/i)).toBeVisible();
  await expect(page.getByPlaceholder(/Structure à la main/i)).toBeVisible();
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

test("onglet Mon profil : contexte éditorial + pré-remplissage IA + sauvegarde", async ({ page }) => {
  await gotoTab(page, "Mon profil");
  await expect(page.getByRole("heading", { name: /Contexte éditorial/i })).toBeVisible();
  // Le bouton de sauvegarde manuelle reste présent…
  await expect(page.getByRole("button", { name: /Sauvegarder/i })).toBeVisible();
  // …et la barre de pré-remplissage IA (qui auto-sauve désormais) aussi.
  await expect(page.getByPlaceholder(/Description, URL LinkedIn ou site web/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /Pré-remplir/i })).toBeVisible();
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

test("Contenu › Mes contenus : liste de posts sauvegardés sans erreur", async ({ page }) => {
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Mes contenus");
  await expect(page.getByRole("heading", { name: /Mes contenus sauvegardés/i })).toBeVisible();
  // Aucun bandeau d'erreur de chargement.
  await expect(page.locator(".error")).toHaveCount(0);
});

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

test("Contenu › Idée du jour : idée + réservoir + opt-in sans erreur", async ({ page }) => {
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Idée du jour");
  await expect(page.getByRole("heading", { name: /^Idée du jour$/i })).toBeVisible();
  // Le réservoir et son switch d'opt-in sont rendus.
  await expect(page.getByRole("heading", { name: /Mon réservoir d'idées/i })).toBeVisible();
  await expect(page.getByText(/Recevoir une idée chaque matin/i)).toBeVisible();
  await expect(page.getByPlaceholder(/Une idée de post/i)).toBeVisible();
  // Aucun bandeau d'erreur de chargement (daily-ideas + idea-seeds).
  await expect(page.locator(".error")).toHaveCount(0);
});

test("Contenu › Idée du jour : les posts de référence ont déménagé (ALE-222)", async ({ page }) => {
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Idée du jour");
  // L'ancienne section ALE-67 n'existe plus ici : un renvoi pointe vers Ma bibliothèque.
  await expect(page.getByRole("heading", { name: /Mes posts de référence/i })).toHaveCount(0);
  await expect(page.getByText(/Tes posts de référence sont désormais dans/i)).toBeVisible();
  await expect(page.locator(".error")).toHaveCount(0);
});
