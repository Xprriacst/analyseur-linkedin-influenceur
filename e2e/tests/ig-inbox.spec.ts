import { test, expect } from "@playwright/test";
import { gotoTab } from "./helpers";

// Inbox de qualification Instagram (epic ALE-195) — LECTURE SEULE : aucun
// message envoyé, aucune génération. On vérifie le rendu plein écran, la
// présence des nouveaux boutons (Simulateur, FAQ) et l'éditeur FAQ.
test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("Inbox : layout plein écran + boutons Simulateur / FAQ / kill-switch", async ({ page }) => {
  await gotoTab(page, "Inbox");
  await expect(page.getByText("Conversations", { exact: false }).first()).toBeVisible();
  // Nouveaux points d'entrée de la barre du haut.
  await expect(page.getByRole("link", { name: /Simulateur/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /FAQ de l'agent/i })).toBeVisible();
  // Kill-switch : l'un des deux libellés selon l'état courant.
  const killOff = page.getByRole("button", { name: /Tout repasser en supervisé/i });
  const killOn = page.getByRole("button", { name: /Réactiver l'autopilot/i });
  await expect(killOff.or(killOn).first()).toBeVisible();
  await expect(page.locator(".error")).toHaveCount(0);
});

test("Inbox : l'éditeur FAQ s'ouvre et se referme (sans enregistrer)", async ({ page }) => {
  await gotoTab(page, "Inbox");
  await page.getByRole("button", { name: /FAQ de l'agent/i }).click();
  await expect(page.getByText(/source de vérité du cerveau/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /Enregistrer la FAQ/i })).toBeVisible();
  await page.getByRole("button", { name: /Fermer la FAQ/i }).click();
  await expect(page.getByRole("button", { name: /Enregistrer la FAQ/i })).toHaveCount(0);
});

test("Simulateur ManyChat : la page /manychat-test se rend connecté (sans envoyer)", async ({ page }) => {
  await page.goto("/manychat-test");
  await expect(page.getByRole("heading", { name: /Simulateur ManyChat/i })).toBeVisible();
  // Formulaire prospect + composer visibles ; on n'envoie rien (coût LLM).
  await expect(page.getByText(/Nom du prospect simulé/i)).toBeVisible();
  await expect(page.getByPlaceholder(/Écris un DM comme le ferait un prospect/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /Envoyer en prospect/i })).toBeDisabled();
});
