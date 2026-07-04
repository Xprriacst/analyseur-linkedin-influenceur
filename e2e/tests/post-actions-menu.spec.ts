import { test, expect, Page } from "@playwright/test";
import { gotoTab, gotoSubTab } from "./helpers";

// ALE-185 : barre d'actions unifiée sur les cartes de post — bouton « Publier ▴ »
// (menu vers le haut : LinkedIn / Programmer / Slack / X selon les réseaux
// connectés) + bouton « ⋯ » (actions secondaires). LECTURE SEULE : on ouvre les
// menus et on referme (Escape), sans jamais cliquer une action de publication.

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

/** Ouvre les deux menus de la première barre d'actions et vérifie leur contenu commun. */
async function checkActionsBar(page: Page, { expectDelete }: { expectDelete: boolean }) {
  const bar = page.locator(".post-actions-bar").first();
  await expect(bar).toBeVisible();

  // Menu principal « Publier » : publier maintenant + programmer, ouvert vers le haut.
  await bar.getByRole("button", { name: /Publier/ }).click();
  const menu = page.locator(".action-menu");
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: /Publier maintenant sur LinkedIn|Publié sur LinkedIn/ })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: /Programmer|Programmé/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);

  // Menu « ⋯ » : actions secondaires (le détail varie selon la section).
  await bar.getByRole("button", { name: "Plus d'actions" }).click();
  await expect(menu).toBeVisible();
  if (expectDelete) {
    await expect(menu.getByRole("menuitem", { name: /Supprimer/ })).toBeVisible();
  }
  // ALE-68 : la génération d'image IA est active (pop-up de prompt) — on vérifie
  // sa présence sans cliquer (le clic préparerait un prompt = appel LLM).
  await expect(menu.getByRole("menuitem", { name: /Générer une image IA/ })).toBeEnabled();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
}

test("Contenu › Mes contenus : menu Publier + ⋯ sur une carte de post (GET mocké)", async ({ page }) => {
  // Le compte de test n'a pas forcément de post sauvegardé et on ne peut pas en
  // générer (lecture seule) : on mocke le GET pour rendre une carte déterministe.
  await page.route("**/me/generated-posts", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify([
          { id: "e2e-ale-185", post: "Post de test ALE-185", topic: "Sujet test", created_at: "2026-07-01T10:00:00Z", media_items: [] },
        ]),
      });
    }
    return route.fallback();
  });
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Mes contenus");
  await expect(page.getByRole("heading", { name: /Mes contenus sauvegardés/i })).toBeVisible();
  await expect(page.locator(".error")).toHaveCount(0);
  await checkActionsBar(page, { expectDelete: true });

  // Le menu « ⋯ » de Mes contenus porte aussi : joindre des images + régénérer.
  const bar = page.locator(".post-actions-bar").first();
  await bar.getByRole("button", { name: "Plus d'actions" }).click();
  const menu = page.locator(".action-menu");
  await expect(menu.getByRole("menuitem", { name: /Joindre des images/ })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: /Régénérer sur ce sujet/ })).toBeVisible();
  // Clic hors du menu → fermeture (comportement Cursor-like).
  await page.getByRole("heading", { name: /Mes contenus sauvegardés/i }).click();
  await expect(menu).toHaveCount(0);
});

test("Contenu › Idée du jour : menu Publier + ⋯ sur le post du jour", async ({ page }) => {
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Idée du jour");
  await expect(page.getByRole("heading", { name: /^Idée du jour$/i })).toBeVisible();
  // Barre présente uniquement si l'idée du jour est un post prêt à publier.
  const hasPost = (await page.locator(".post-actions-bar").count()) > 0;
  test.skip(!hasPost, "Pas de post du jour sur le compte de test.");
  await checkActionsBar(page, { expectDelete: false });
});
