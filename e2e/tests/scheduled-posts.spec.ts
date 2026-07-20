import { test, expect } from "@playwright/test";
import { gotoTab, gotoSubTab } from "./helpers";

// Posts programmés (Ma bibliothèque) : l'image jointe au post doit être visible —
// badge « image » sur la carte, aperçu dans la pop-up. LECTURE SEULE : statut
// LinkedIn et liste des posts programmés mockés, aucune programmation réelle.

const onePxPng =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

test("Contenu › Ma bibliothèque : un post programmé avec image montre le badge et l'aperçu", async ({ page }) => {
  // La section « Posts programmés » ne se rend que si LinkedIn est connecté.
  // account_name fourni, sinon le front déclenche un refresh de backfill.
  await page.route("**/me/linkedin/status", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ configured: true, connected: true, account_id: "acc-e2e", account_name: "Compte de test" }),
      });
    }
    return route.fallback();
  });
  await page.route("**/me/linkedin/scheduled", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "sched-e2e-img",
            post_text: "Post programmé de test avec image.",
            scheduled_at: "2027-01-05T09:00:00Z",
            status: "pending",
            slack_status: "validated",
            media_items: [{ type: "image", url: onePxPng }],
            created_at: "2026-07-20T10:00:00Z",
          },
          {
            id: "sched-e2e-noimg",
            post_text: "Post programmé de test sans image.",
            scheduled_at: "2027-01-06T09:00:00Z",
            status: "pending",
            slack_status: "validated",
            media_items: [],
            created_at: "2026-07-20T10:00:00Z",
          },
        ]),
      });
    }
    return route.fallback();
  });

  await page.goto("/");
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Ma bibliothèque");
  await expect(page.getByRole("heading", { name: /Posts programmés/i })).toBeVisible();

  // Badge « image » sur la carte du post qui en a une, pas sur l'autre.
  const cardWithImage = page.getByRole("button", { name: /Ouvrir « Post programmé de test avec image/ });
  await expect(cardWithImage).toBeVisible();
  await expect(cardWithImage.locator(".lib-tag", { hasText: /^image$/ })).toBeVisible();
  const cardWithout = page.getByRole("button", { name: /Ouvrir « Post programmé de test sans image/ });
  await expect(cardWithout.locator(".lib-tag", { hasText: /^image$/ })).toHaveCount(0);

  // La pop-up affiche l'aperçu de l'image jointe.
  await cardWithImage.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(/1 image jointe — elle partira avec le post/)).toBeVisible();
  await expect(dialog.getByAltText("Image jointe 1")).toBeVisible();
});
