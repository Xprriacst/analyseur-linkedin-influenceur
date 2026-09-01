import { test, expect } from "@playwright/test";

/**
 * Page de vente `/offre` — les verbatims clients sont des citations réelles.
 * Une paraphrase ou un nom inventé passerait pour du marketing ; le spec
 * verrouille le mot-à-mot.
 */
test.describe("Landing /offre", () => {
  test("affiche les verbatims de Sacha et Joëlle tels quels", async ({ page }) => {
    await page.goto("/offre");
    await expect(
      page.getByText("Pour être honnête avec vous les gars je suis 100% satisfait de votre accompagnement"),
    ).toBeVisible();
    await expect(
      page.getByText(/très contente de ce premier mois de collaboration/),
    ).toBeVisible();
    await expect(page.getByText("Sacha", { exact: true })).toBeVisible();
    await expect(page.getByText("Joëlle", { exact: true })).toBeVisible();
  });
});
