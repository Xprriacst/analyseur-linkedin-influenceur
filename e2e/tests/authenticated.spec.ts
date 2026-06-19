import { test, expect } from "@playwright/test";
import { gotoTab } from "./helpers";

// Parcours authentifiés en LECTURE SEULE (pas de génération → aucun coût LLM/Apify).
test.beforeEach(async ({ page }) => {
  await page.goto("/");
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

test("onglet Mes contenus : liste posts/idées sans erreur", async ({ page }) => {
  await gotoTab(page, "Mes contenus");
  await expect(page.getByRole("heading", { name: /Mes contenus sauvegardés/i })).toBeVisible();
  // Les deux sous-onglets de bascule.
  await expect(page.getByRole("button", { name: /^Posts \(/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Idées \(/ })).toBeVisible();
  // Aucun bandeau d'erreur de chargement.
  await expect(page.locator(".error")).toHaveCount(0);
  // Bascule vers les idées sans crash.
  await page.getByRole("button", { name: /^Idées \(/ }).click();
  await expect(page.locator(".error")).toHaveCount(0);
});

test("onglet Générateur de posts : formulaires rendus", async ({ page }) => {
  await gotoTab(page, "Générateur de posts");
  await expect(page.getByRole("heading", { name: /Idées de posts/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Générer des posts/i })).toBeVisible();
  await expect(page.getByPlaceholder(/Sujet du post/i)).toBeVisible();
});

test("onglet Assistant : interface chat rendue", async ({ page }) => {
  await gotoTab(page, "Assistant");
  // L'onglet doit devenir actif sans rediriger vers l'auth (donc session OK).
  await expect(page.locator(".nav-item.active", { hasText: "Assistant" })).toBeVisible();
});
