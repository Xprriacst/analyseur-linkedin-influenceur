import { Page, expect } from "@playwright/test";

export const CREDS = {
  email: process.env.E2E_EMAIL || "qa.playwright@lkd-outreach.app",
  password: process.env.E2E_PASSWORD || "Lkd!Test2026",
};

/** Se connecte depuis `/pilote` et attend la session Supabase.
 *
 *  ⚠️ L'app n'a plus de porte d'entrée anonyme : un visiteur non connecté sur `/`
 *  est renvoyé sur la page de vente `/pilote`, qui porte aussi la connexion. Le
 *  modal e-mail/mot de passe du header n'est donc plus atteignable sans compte.
 */
export async function loginOnPilote(page: Page, creds = CREDS) {
  await page.goto("/pilote");
  // Le formulaire s'ouvre en mode « Crée ton compte » : on bascule sur la
  // connexion (le champ de confirmation disparaît, c'est le témoin du mode).
  await page.locator(".pilote-switch").click();
  await expect(page.locator("#pilote-password2")).toHaveCount(0);
  await page.locator("#pilote-email").fill(creds.email);
  await page.locator("#pilote-password").fill(creds.password);
  await page.locator("button.pilote-submit").click();
  // La session Supabase est stockée en localStorage (sb-<ref>-auth-token).
  await page.waitForFunction(
    () => Object.keys(localStorage).some((k) => /sb-.*-auth-token/.test(k)),
    undefined,
    { timeout: 30_000 }
  );
}

export const login = loginOnPilote;

/** Navigue vers un onglet de la sidebar par son libellé. */
export async function gotoTab(page: Page, label: string) {
  await page.locator(".nav-item", { hasText: label }).click();
  await expect(page.locator(".nav-item.active", { hasText: label })).toBeVisible();
}

/** Navigue vers un sous-onglet (barre `.tab`) par son libellé, ex. dans « Contenu ». */
export async function gotoSubTab(page: Page, label: string) {
  await page.locator(".tab", { hasText: label }).click();
  await expect(page.locator(".tab.active", { hasText: label })).toBeVisible();
}
