import { test, expect, Page } from "@playwright/test";
import { gotoTab, gotoSubTab } from "./helpers";

/**
 * Test de non-régression de l'ISOLATION CROSS-COMPTE (fix PR #102).
 *
 * Bug reproduit : le compte A génère un lot d'idées (state local `ideaBatch` de
 * DailyIdeasView, jamais purgé par l'ancien code) → on bascule sur le compte B
 * dans le MÊME onglet, sans recharger la page → sans le fix, B voyait les idées
 * de A. Le fix (`key={user.id}` sur <main>) remonte le sous-arbre au changement
 * d'utilisateur, donc B repart à zéro.
 *
 * ⚠️ Ce test GÉNÈRE un lot d'idées (1 appel Anthropic, ~quelques centimes) — il
 * n'est donc PAS en lecture seule, contrairement au reste de la suite. À lancer
 * ponctuellement (non inclus dans le smoke).
 *
 * Prérequis : 2 comptes de test (A a au moins 1 influenceur analysé pour /ideas).
 */

const A = {
  email: process.env.E2E_EMAIL || "qa.playwright@lkd-outreach.app",
  password: process.env.E2E_PASSWORD || "Lkd!Test2026",
};
const B = {
  email: process.env.E2E_EMAIL_B || "qa.playwright.b@lkd-outreach.app",
  password: process.env.E2E_PASSWORD_B || "Lkd!Test2026",
};

const tokenPresent = () =>
  Object.keys(localStorage).some((k) => /sb-.*-auth-token/.test(k));

/** Connexion via le modal, SANS recharger la page (pour rester dans la même
 *  instance SPA — condition de reproduction du bug). */
async function loginViaModal(page: Page, creds: { email: string; password: string }) {
  await page.getByRole("button", { name: "Se connecter" }).first().click();
  await page.getByPlaceholder("toi@exemple.com").fill(creds.email);
  await page.getByPlaceholder("••••••••").fill(creds.password);
  await page.getByRole("button", { name: "Se connecter" }).last().click();
  await page.waitForFunction(() => Object.keys(localStorage).some((k) => /sb-.*-auth-token/.test(k)), undefined, { timeout: 30_000 });
}

test("isolation cross-compte : B ne voit pas les idées générées par A", async ({ page }) => {
  test.setTimeout(180_000); // cold start Render + génération réelle

  // 1. Charge l'app UNE fois ; toute la suite reste dans la même instance SPA.
  await page.goto("/");
  await loginViaModal(page, A);

  // 2. Compte A génère un lot d'idées.
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Idée du jour");
  await page.locator(".ideas-batch-section").getByRole("button", { name: /Générer/ }).click();
  await expect(page.locator(".idea-line-item").first()).toBeVisible({ timeout: 120_000 });
  const aCount = await page.locator(".idea-line-item").count();
  expect(aCount).toBeGreaterThan(0);
  const aFirstIdea = (await page.locator(".idea-line-text").first().innerText()).trim();

  // 3. Déconnexion in-app — PAS de page.goto/reload : la SPA reste montée
  //    (c'est la condition qui faisait fuiter le state des composants enfants).
  await page.locator(".header-user").click();
  await page.waitForFunction(() => !Object.keys(localStorage).some((k) => /sb-.*-auth-token/.test(k)), undefined, { timeout: 15_000 });

  // 4. Connexion compte B (toujours sans reload).
  await loginViaModal(page, B);

  // 5. B ouvre Idée du jour : il ne doit voir AUCUNE idée (ni celles de A).
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Idée du jour");
  await expect(page.getByRole("heading", { name: /^Idée du jour$/i })).toBeVisible();
  await expect(page.locator(".idea-line-item")).toHaveCount(0);
  await expect(page.getByText(aFirstIdea, { exact: false })).toHaveCount(0);
});
