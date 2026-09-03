import { test, expect } from "@playwright/test";

/**
 * Anciennes portes d'entrée → `/pilote` (décision d'Alex du 2026-09-03 : une
 * seule porte). Ce fichier REMPLACE `audit-funnel`, `founders-funnel` et
 * `offre-landing` : leurs tunnels ne sont plus atteignables, garder leurs
 * specs aurait laissé la CI rouge en permanence.
 *
 * ⚠️ Ce qui a été perdu volontairement, pour mémoire : `/start` était le
 * tunnel d'audit gratuit qui finissait sur le Calendly de Tom, et `/essai`
 * l'écran des comptes non éligibles à l'essai. Les pages sont toujours dans
 * le dépôt — rouvrir l'une d'elles, c'est retirer une ligne de next.config.
 */
const LEGACY = ["/onboarding", "/founders", "/start", "/essai", "/offre"];

for (const path of LEGACY) {
  test(`${path} renvoie sur la page de vente`, async ({ page }) => {
    await page.goto(path);
    await page.waitForURL(/\/pilote$/, { timeout: 30_000 });
    await expect(
      page.locator(".pilote-form-card").getByRole("heading", { name: /Crée ton compte/i })
    ).toBeVisible();
  });
}

test("la landing porte la promesse BDR et les chiffres de preuve", async ({ page }) => {
  await page.goto("/pilote");
  // Le sigle BDR ne parle pas aux freelances : le titre ne vaut que si la
  // page l'explique. Si l'explication saute, le titre devient du jargon.
  // (La page porte deux <h1> — hero + formulaire : on vise celui du hero.)
  await expect(page.locator("h1.pilote-h1")).toContainText(/BDR/);
  await expect(page.locator(".pilote-lead")).toContainText(/commercial qui va chercher les clients/i);
  for (const promesse of [
    /Analyse complète de ton profil LinkedIn ou de ton site web/i,
    /stratégie d'acquisition définie pour ta niche/i,
    /post par jour, écrit pour toi/i,
    /prospects identifiés, avec des messages personnalisés/i,
  ]) {
    await expect(page.locator(".pilote-pills")).toContainText(promesse);
  }
  // Chiffres mesurés en base, pas arrondis vers le haut (cf. lib/founders.ts).
  await expect(page.locator(".pilote-proof-foot")).toContainText("50+");
  await expect(page.locator(".pilote-proof-foot")).toContainText("3 000+");
});
