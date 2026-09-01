import { test, expect } from "@playwright/test";

// Plan « Pilote gratuit » — 1 post / jour, 3 contacts / jour (backend mocké, 0 coût).
//
// Ce que ce spec verrouille, et qui casserait EN SILENCE sinon :
//   1. le plan vient du SERVEUR (`GET /me/plan`) et gagne contre le localStorage —
//      sans ça, un compte gratuit qui a cliqué « Expert » une fois ne reverrait
//      plus jamais son plan du jour ;
//   2. « expert » n'est jamais persisté pour ce plan (retour au Pilote au reload) ;
//   3. un refus de quota (402) ARRIVE À L'ÉCRAN. C'est le point le plus fragile :
//      le serveur bloque proprement, mais si le message n'est pas affiché, le
//      client voit un bouton qui « ne fait rien » et croit l'app cassée.

const MOCK_PILOT = {
  plan: {
    userName: "Alex",
    dayNumber: 1,
    weekNumber: 36,
    weeklyDone: 0,
    weeklyTotal: 3,
    author: { name: "Alex Test", headline: "Builder SaaS", initials: "AT" },
    post: {
      structure: "Récit + insight",
      hook: "La prospection LinkedIn ne devrait pas être un second métier.",
      body: "Voici ce que j'ai automatisé cette semaine.",
    },
    followProfiles: [],
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
      profiles: [],
      frequency: "1 post / jour",
      target: "Fondateurs SaaS",
      structureHint: "Direct",
    },
  },
  meta: {
    post_id: "post-1",
    post_source: "generated",
    post_text: "La prospection LinkedIn ne devrait pas être un second métier.",
    post_empty: false,
    media_items: [],
    follow_handles: {},
    linkedin_outreach_connected: true,
    linkedin_publish_connected: true,
    contacts_blocked_reason: null,
  },
};

const PILOT_FREE_PLAN = {
  plan: "pilot_free",
  pilot_free: true,
  quotas: {
    posts_per_day: 1,
    leads_per_day: 3,
    posts_used_today: 1,
    leads_used_today: 3,
  },
};

async function mockPilotFreeBackend(page: import("@playwright/test").Page) {
  await page.route("**/me/plan", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(PILOT_FREE_PLAN) }),
  );
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

test.describe("Plan Pilote gratuit", () => {
  test("le plan vient du serveur et ramène le compte sur le Mode Pilote", async ({ page }) => {
    // Le navigateur dit « expert » : c'est le plan serveur qui doit trancher.
    await page.addInitScript(() => {
      localStorage.setItem("lkd_interface_mode", "expert");
    });
    await mockPilotFreeBackend(page);
    await page.goto("/");

    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });
    await expect(page.getByRole("tab", { name: "Pilote" })).toHaveAttribute("aria-selected", "true");
    await expect(page.locator(".sidebar")).toHaveCount(0);
  });

  test("le mode Expert n'est jamais persisté pour un compte gratuit", async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("lkd_interface_mode", "pilot");
    });
    await mockPilotFreeBackend(page);
    await page.goto("/");

    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });

    // Le toggle reste cliquable (les écrans de connexion vivent côté Expert),
    // mais le choix ne doit pas survivre au rechargement.
    await page.getByRole("tab", { name: "Expert" }).click();
    await expect(page.locator(".sidebar")).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => localStorage.getItem("lkd_interface_mode")))
      .toBe("pilot");
  });

  test("un refus de quota contacts est affiché au client, pas avalé", async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("lkd_interface_mode", "pilot");
    });
    await mockPilotFreeBackend(page);

    let inviteCalled = false;
    await page.route("**/me/leads/*/invite", (route) => {
      inviteCalled = true;
      route.fulfill({
        status: 402,
        contentType: "application/json",
        body: JSON.stringify({
          detail:
            "Mode Pilote : 3 contacts par jour (3/3 sur 24 h). Reviens demain pour les suivants. Passe en mode Expert (abonnement) pour continuer sans attendre.",
        }),
      });
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });

    await page.getByRole("button", { name: /Camille Dupont/i }).click();
    await page.getByRole("button", { name: /^Inviter$/i }).click();

    await expect.poll(() => inviteCalled).toBe(true);
    await expect(page.getByText(/3 contacts par jour/i)).toBeVisible();
    // Le lead ne doit PAS passer en « Invitation envoyée » sur un refus.
    await expect(page.getByRole("button", { name: /Invitation envoyée/i })).toHaveCount(0);
  });
});
