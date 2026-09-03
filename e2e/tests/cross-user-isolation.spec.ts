import { test, expect, Page } from "@playwright/test";
import { gotoTab, gotoSubTab, loginOnPilote } from "./helpers";

/**
 * Test de non-régression de l'ISOLATION CROSS-COMPTE (fix PR #102).
 *
 * Bug reproduit : le compte A génère un lot d'idées (state local jamais purgé par
 * l'ancien code) → on bascule sur le compte B dans le MÊME onglet → sans le fix,
 * B voyait les idées de A. Le fix (`key={user.id}` sur <main>) remonte le
 * sous-arbre au changement d'utilisateur, donc B repart à zéro.
 *
 * ⚠️ Depuis que `/` renvoie les visiteurs sur `/pilote`, la déconnexion sort de
 * l'app : le remontage est désormais garanti par la navigation elle-même, et la
 * condition d'origine (SPA qui reste montée) n'est plus reproductible depuis
 * l'interface. Ce test vérifie donc le RÉSULTAT (B ne voit rien de A), pas le
 * mécanisme — il reste le filet si une future page gardait l'app montée d'un
 * compte à l'autre. La purge de `_genCache`, elle, est toujours indispensable :
 * ce cache est module-level, il survit à un remontage de composant.
 *
 * ALE-286 : le lot d'idées se génère désormais dans le parcours du Générateur (le
 * sous-onglet « Idée du jour » a quitté la vue agence) — le test suit la même
 * surface, au même coût. Il couvre en plus la file de posts, dont le cache est
 * module-level : une clé oubliée dans la purge de `_genCache` ferait réapparaître
 * le brouillon du compte précédent.
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

/** Connexion depuis `/pilote` (seule porte d'entrée sans compte), puis attente
 *  de l'app : la landing renvoie sur `/` dès que la session existe. */
async function loginAndEnterApp(page: Page, creds: { email: string; password: string }) {
  await loginOnPilote(page, creds);
  await expect(page.locator(".app-shell, .pilot-app-layout").first()).toBeVisible({ timeout: 60_000 });
}

test("isolation cross-compte : B ne voit pas les idées générées par A", async ({ page }) => {
  test.setTimeout(180_000); // cold start Render + génération réelle

  // 1. Connexion du compte A depuis la page de vente.
  await loginAndEnterApp(page, A);

  // 2. Compte A génère un lot d'idées, via le parcours du Générateur (ALE-286).
  //    On s'arrête AVANT le lancement des posts : c'est l'appel /ideas qu'on veut,
  //    pas 15 crédits de génération.
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Générateur de posts");
  await page.getByRole("button", { name: /Générer un post/i }).click();
  await page.getByRole("button", { name: /Je n'ai pas d'idée/i }).click();
  await expect(page.locator(".wizard-idea-line").first()).toBeVisible({ timeout: 120_000 });
  const aCount = await page.locator(".wizard-idea-line").count();
  expect(aCount).toBeGreaterThan(0);
  const aFirstIdea = (await page.locator(".wizard-idea-line").first().innerText()).trim();
  await page.keyboard.press("Escape");

  // 3. Déconnexion in-app. Elle renvoie désormais sur `/pilote` : c'est ce
  //    retour à la landing qui garantit que rien de A ne reste à l'écran.
  await page.locator(".header-user").click();
  await page.waitForFunction(() => !Object.keys(localStorage).some((k) => /sb-.*-auth-token/.test(k)), undefined, { timeout: 15_000 });

  // 4. Connexion du compte B, depuis la landing où la déconnexion nous a posés.
  await page.waitForURL(/\/pilote$/, { timeout: 30_000 });
  await loginAndEnterApp(page, B);

  // 5. B ouvre le Générateur : ni les posts de A dans la file, ni ses idées dans
  //    le parcours (le cache module-level du Générateur doit avoir été purgé).
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Générateur de posts");
  await expect(page.getByRole("button", { name: /Générer un post/i })).toBeVisible();
  await expect(page.getByText(aFirstIdea, { exact: false })).toHaveCount(0);

  await page.getByRole("button", { name: /Générer un post/i }).click();
  await expect(page.getByRole("heading", { name: /Par où on commence/i })).toBeVisible();
  await expect(page.locator(".wizard-idea-line")).toHaveCount(0);
});
