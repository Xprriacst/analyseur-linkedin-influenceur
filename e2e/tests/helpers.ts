import { Page, expect } from "@playwright/test";

export const CREDS = {
  email: process.env.E2E_EMAIL || "qa.playwright@lkd-outreach.app",
  password: process.env.E2E_PASSWORD || "Lkd!Test2026",
};

/** Ouvre le modal de connexion, saisit les identifiants et attend la session Supabase. */
export async function login(page: Page) {
  await page.goto("/");
  // Bouton du header (le seul "Se connecter" tant que le modal n'est pas ouvert).
  await page.getByRole("button", { name: "Se connecter" }).first().click();
  await page.getByPlaceholder("toi@exemple.com").fill(CREDS.email);
  await page.getByPlaceholder("••••••••").fill(CREDS.password);
  // Une fois le modal ouvert, le bouton de soumission est le dernier "Se connecter".
  await page.getByRole("button", { name: "Se connecter" }).last().click();
  // La session Supabase est stockée en localStorage (sb-<ref>-auth-token).
  await page.waitForFunction(
    () => Object.keys(localStorage).some((k) => /sb-.*-auth-token/.test(k)),
    undefined,
    { timeout: 30_000 }
  );
}

/** Navigue vers un onglet de la sidebar par son libellé. */
export async function gotoTab(page: Page, label: string) {
  await page.locator(".nav-item", { hasText: label }).click();
  await expect(page.locator(".nav-item.active", { hasText: label })).toBeVisible();
}
