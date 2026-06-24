import { test, expect } from "@playwright/test";

// Écrans publics — aucun login, aucun coût backend.
test.describe("Landing publique", () => {
  test("la page se charge avec le titre et la navigation", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/Cibl/i);
    for (const label of ["Contenu", "Veille", "Agent IA", "Leads", "Mon profil"]) {
      await expect(page.locator(".nav-item", { hasText: label })).toBeVisible();
    }
  });

  test("le modal de connexion s'ouvre", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Se connecter" }).first().click();
    await expect(page.getByPlaceholder("toi@exemple.com")).toBeVisible();
    await expect(page.getByPlaceholder("••••••••")).toBeVisible();
  });

  test("la sidebar repliée affiche un bouton pour la rouvrir", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Réduire la sidebar" }).click();

    await expect(page.locator(".sidebar")).toHaveClass(/sidebar-collapsed/);
    await expect(page.getByRole("button", { name: "Étendre la sidebar" })).toBeVisible();

    await page.getByRole("button", { name: "Étendre la sidebar" }).click();
    await expect(page.locator(".sidebar")).not.toHaveClass(/sidebar-collapsed/);
    await expect(page.getByRole("button", { name: "Réduire la sidebar" })).toBeVisible();
  });
});
