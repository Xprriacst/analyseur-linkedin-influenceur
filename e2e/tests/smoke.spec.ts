import { test, expect } from "@playwright/test";

// Écrans publics — aucun login, aucun coût backend.
test.describe("Landing publique", () => {
  test("la page se charge avec le titre et la navigation", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/Strategy Decoder/i);
    for (const label of ["Analyser", "Mon profil", "Générateur de posts", "Mes contenus", "Dashboard"]) {
      await expect(page.locator(".nav-item", { hasText: label })).toBeVisible();
    }
  });

  test("le modal de connexion s'ouvre", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Se connecter" }).first().click();
    await expect(page.getByPlaceholder("toi@exemple.com")).toBeVisible();
    await expect(page.getByPlaceholder("••••••••")).toBeVisible();
  });
});
