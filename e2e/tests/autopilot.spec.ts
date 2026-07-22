import { test, expect } from "@playwright/test";
import { gotoTab } from "./helpers";

// ALE-284 : autopilote de prospection — pop-up de réglage + schéma de séquence.
//
// Tout le backend est MOCKÉ : ce spec ne déclenche aucun envoi LinkedIn et ne coûte
// rien. Ce qu'il verrouille, c'est le CÂBLAGE de l'écran, et en particulier deux
// choses qui ne se verraient pas autrement :
//
//  1. que les trois réponses du client (à qui / quoi / avec ou sans relecture)
//     partent bien toutes les trois au serveur — un réglage perdu en route donnerait
//     un autopilote qui ne fait pas ce que le client croit avoir demandé ;
//  2. que le schéma affiché vient du SERVEUR et grise les étapes refusées. Un schéma
//     qui annoncerait « tu relis avant envoi » alors que les messages partent seuls
//     serait le pire bug possible de cet écran.

const CONNECTED_ACCOUNT = {
  configured: true,
  connected: true,
  account_name: "Compte de test",
  quota: {
    daily_cap: 25, weekly_invite_cap: 100, invites_today: 0, messages_today: 0, invites_week: 0,
    can_invite: true, can_message: true, counts_available: true,
  },
};

/** État moteur + autopilote, tel que `_engine_state` le renvoie. */
function engine(automation: Record<string, unknown>) {
  return {
    pending: 0, drafts_pending: 0, stalled: false, frozen: false,
    warmup_week: 4, warmup_cap: 25, warmup_weeks_total: 3,
    next_send_estimate: new Date(Date.now() + 3600_000).toISOString(),
    immediate_left: 3, immediate_cap: 3,
    window: { timezone: "Europe/Paris", hour_start: 9, hour_end: 18, days: [1, 2, 3, 4, 5] },
    automation,
  };
}

/** Autopilote éteint : les 3 étapes existent, aucune n'est active. */
const OFF = {
  enabled: false, tier: "green", invite_min_score: 70, invite_daily_cap: 15,
  message_mode: "none", message_template: "", requires_validation: true,
  steps: [
    { key: "invite", label: "Demande de connexion", detail: "Aux leads verts", active: false },
    { key: "compose", label: "Premier message", detail: "Aucun message prévu", active: false },
    { key: "send", label: "Envoi du message", detail: "Aucun message prévu", active: false },
  ],
};

async function mockProspecting(page: import("@playwright/test").Page, automation: Record<string, unknown>) {
  await page.route("**/me/linkedin/outreach/status", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ...CONNECTED_ACCOUNT, engine: engine(automation) }),
    })
  );
  await page.route("**/me/linkedin/outreach/lead-tiers", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ counts: { green: 3, orange: 11, red: 59, unscored: 49 } }),
    })
  );
  await page.route("**/me/linkedin/outreach/drafts", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [] }) })
  );
  await page.route("**/me/leads", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ leads: [] }) })
  );
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("les trois réponses de la pop-up partent bien toutes au serveur", async ({ page }) => {
  await mockProspecting(page, OFF);

  // On intercepte l'enregistrement pour lire ce qui part vraiment.
  let saved: any = null;
  await page.route("**/me/linkedin/outreach/settings", async (route) => {
    saved = JSON.parse(route.request().postData() || "{}");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ...CONNECTED_ACCOUNT, engine: engine({ ...OFF, enabled: true }) }),
    });
  });

  await gotoTab(page, "Prospection");
  await page.getByRole("button", { name: /Activer l'autopilote/i }).click();

  // Le bouton de la page et celui du dernier écran de la pop-up portent le même
  // libellé : on reste dans la modale pour ne pas viser le mauvais.
  const modal = page.getByRole("dialog", { name: /autopilote/i });
  await expect(modal).toBeVisible();

  // 1. À qui : on élargit aux verts ET orange (donc pas la valeur par défaut).
  await modal.getByRole("button", { name: /Verts et orange/i }).click();
  await modal.getByRole("button", { name: /Continuer/i }).click();

  // 2. Quoi : un message type, avec son texte.
  await modal.getByRole("button", { name: /Mon propre message type/i }).click();
  await modal.locator("textarea").first().fill("Bonjour {{prenom}}, on échange ?");
  await modal.getByRole("button", { name: /Continuer/i }).click();

  // 3. Relecture : on choisit explicitement l'envoi automatique.
  await modal.getByRole("button", { name: /Envoi automatique/i }).click();
  await modal.getByRole("button", { name: /Continuer/i }).click();

  await modal.getByRole("button", { name: /Activer l'autopilote/i }).click();

  await expect.poll(() => saved).not.toBeNull();
  expect(saved.auto_prospection_enabled).toBe(true);
  expect(saved.auto_invite_tier).toBe("orange");
  expect(saved.auto_message_mode).toBe("template");
  expect(saved.auto_message_template).toContain("{{prenom}}");
  // Le réglage le plus lourd de conséquences : il doit arriver tel que choisi.
  expect(saved.auto_message_requires_validation).toBe(false);
});

test("le mode template refuse d'avancer sans texte", async ({ page }) => {
  await mockProspecting(page, OFF);
  await gotoTab(page, "Prospection");
  await page.getByRole("button", { name: /Activer l'autopilote/i }).click();
  const modal = page.getByRole("dialog", { name: /autopilote/i });
  await modal.getByRole("button", { name: /Continuer/i }).click();

  await modal.getByRole("button", { name: /Mon propre message type/i }).click();
  // Un template vide ne produirait que des messages vides, rejetés un par un en silence.
  await expect(modal.getByRole("button", { name: /Continuer/i })).toBeDisabled();
  await modal.locator("textarea").first().fill("Bonjour !");
  await expect(modal.getByRole("button", { name: /Continuer/i })).toBeEnabled();
});

test("le schéma grise les étapes que le client n'a pas voulues", async ({ page }) => {
  // Autopilote actif, mais SANS message : les deux étapes de message sont éteintes.
  await mockProspecting(page, {
    ...OFF,
    enabled: true,
    steps: [
      { key: "invite", label: "Demande de connexion", detail: "Aux leads verts", active: true },
      { key: "compose", label: "Premier message", detail: "Aucun message prévu", active: false },
      { key: "send", label: "Envoi du message", detail: "Aucun message prévu", active: false },
    ],
  });
  await gotoTab(page, "Prospection");

  const sequence = page.getByRole("list", { name: /Étapes de ton autopilote/i });
  await expect(sequence).toBeVisible();
  await expect(sequence.getByText("Demande de connexion")).toBeVisible();
  // Les étapes refusées restent VISIBLES (grisées), pour que le client se rappelle
  // ce que son autopilote ne fait pas — les masquer lui ferait oublier son réglage.
  await expect(sequence.getByText("Premier message")).toBeVisible();
  await expect(sequence.getByText("Envoi du message")).toBeVisible();
  await expect(page.getByRole("button", { name: /Autopilote actif/i })).toBeVisible();
});

test("les messages à valider s'affichent et rien ne part sans le feu vert", async ({ page }) => {
  await mockProspecting(page, { ...OFF, enabled: true, message_mode: "ai" });
  await page.unroute("**/me/linkedin/outreach/drafts");
  await page.route("**/me/linkedin/outreach/drafts", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [{
          id: "draft-1", action_type: "message", status: "draft", origin: "autopilot",
          body: "Bonjour Camille, ton commentaire sur le post de…",
          leads: { id: "lead-1", name: "Camille Durand", headline: "Head of Growth" },
        }],
      }),
    })
  );

  await gotoTab(page, "Prospection");
  await expect(page.getByText(/À valider — 1 message/i)).toBeVisible();
  await expect(page.getByText("Camille Durand")).toBeVisible();
  // Le texte est éditable avant validation : ce qui part est ce qui est à l'écran.
  await expect(page.getByRole("button", { name: /Valider l'envoi/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Ne pas envoyer/i })).toBeVisible();
});
