import { test, expect } from "@playwright/test";

// Mode Pilote — câblage réel (backend mocké, 0 Anthropic / 0 Apify).
// Vérifie : atterrissage Pilote, bascule Expert, invite → file outreach.

const MOCK_PILOT = {
  plan: {
    userName: "Alex",
    dayNumber: 1,
    weekNumber: 35,
    weeklyDone: 1,
    weeklyTotal: 3,
    author: {
      name: "Alex Test",
      headline: "Builder SaaS",
      initials: "AT",
    },
    post: {
      structure: "Récit + insight",
      hook: "La prospection LinkedIn ne devrait pas être un second métier.",
      body: "Voici ce que j'ai automatisé cette semaine.\n\nEt toi, tu passes combien de temps dessus ?",
    },
    followProfiles: [
      {
        id: "inf-1",
        name: "Romain Cornille",
        handle: "@romain",
        reason: "SaaS B2B — repéré dans ton analyse.",
        initials: "RC",
        accent: "linear-gradient(135deg, #6366f1, #4338ca)",
      },
    ],
    contacts: [
      {
        id: "lead-42",
        name: "Camille Dupont",
        role: "Fondatrice",
        company: "Acme",
        score: 82,
        initials: "CD",
        accent: "linear-gradient(135deg, #10b981, #047857)",
        message: "Bonjour Camille — ton profil correspond à mon ICP.",
      },
    ],
    strategy: {
      profiles: ["@romain"],
      frequency: "3 posts / semaine · lun 9h, mer 9h",
      target: "Fondateurs SaaS · outbound assisté",
      structureHint: "Direct — objectif : générer des conversations",
    },
  },
  meta: {
    post_id: "post-1",
    post_source: "generated",
    post_text: "La prospection LinkedIn ne devrait pas être un second métier.",
    post_empty: false,
    media_items: [],
    follow_handles: { "inf-1": "romain" },
    linkedin_outreach_connected: true,
    linkedin_publish_connected: true,
    contacts_blocked_reason: null,
  },
};

async function mockPilotBackend(page: import("@playwright/test").Page) {
  await page.route("**/me/pilot/today", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(MOCK_PILOT) }),
  );
  await page.route("**/me/profile", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        display_name: "Alex Test",
        brand_name: "Cibl",
        business_description: "SaaS",
      }),
    }),
  );
}

test.describe("Mode Pilote", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("lkd_interface_mode", "pilot");
    });
    await mockPilotBackend(page);
    await page.goto("/");
  });

  test("un compte agence atterrit sur le Mode Pilote", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });
    await expect(page.getByRole("heading", { name: /Post du jour/i })).toBeVisible();
    await expect(page.locator(".sidebar")).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "Pilote" })).toHaveAttribute("aria-selected", "true");
  });

  test("le toggle Expert affiche la sidebar", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });
    await page.getByRole("tab", { name: "Expert" }).click();
    await expect(page.locator(".sidebar")).toBeVisible();
    await expect(page.locator(".nav-item", { hasText: "Contenu" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Expert" })).toHaveAttribute("aria-selected", "true");
  });

  test("Inviter appelle l’API outreach existante (file, pas d’envoi immédiat)", async ({ page }) => {
    let inviteCalled = false;
    await page.route("**/me/leads/*/invite", (route) => {
      inviteCalled = true;
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ ok: true, queued: true, status: "invite_queued" }),
      });
    });

    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });
    await page.getByRole("button", { name: /^Inviter$/i }).click();
    await expect.poll(() => inviteCalled).toBe(true);
    await expect(page.getByRole("button", { name: /Invitation envoyée/i })).toBeVisible();
  });
});
