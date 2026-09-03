import { test, expect } from "@playwright/test";

// Écrans publics — aucun login, aucun coût backend.
test.describe("Porte d'entrée publique", () => {
  test("un visiteur non connecté est envoyé sur la page de vente", async ({ page }) => {
    // L'app n'a plus d'aperçu anonyme : la seule porte d'entrée est `/pilote`
    // (landing → compte → onboarding → vue du jour). Avant, le visiteur tombait
    // sur un aperçu de l'app dont les boutons ouvraient une fenêtre
    // e-mail/mot de passe — il ne voyait jamais ce qu'on lui vend.
    await page.goto("/");
    await page.waitForURL(/\/pilote$/, { timeout: 30_000 });
    await expect(
      page.locator(".pilote-form-card").getByRole("heading", { name: /Crée ton compte/i })
    ).toBeVisible();
    // Et l'app elle-même n'est pas laissée derrière : pas de sidebar à explorer.
    await expect(page.locator(".sidebar")).toHaveCount(0);
  });
});
