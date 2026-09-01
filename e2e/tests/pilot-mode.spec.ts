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

const FOLLOW_SUGGESTIONS = [
  {
    handle: "marie-coach",
    name: "Marie Coach",
    headline: "Coaching business pour indépendants",
    profile_url: "https://www.linkedin.com/in/marie-coach/",
    follower_count: 5200,
    matched_keywords: ["coaching", "indépendants"],
  },
];

/** Compte les appels au endpoint de suggestions — c'est ce compteur qui prouve
 *  le chargement paresseux (0 tant que le panneau est replié). */
function mockFollowSuggestions(
  page: import("@playwright/test").Page,
  suggestions: unknown[],
  counter: { calls: number },
) {
  return page.route("**/me/follow-suggestions", (route) => {
    counter.calls += 1;
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ suggestions, followed_count: 0, cap: 5 }),
    });
  });
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
    await expect(page.getByRole("region", { name: "À suivre" })).toHaveCount(0);
    await page.getByRole("button", { name: /Camille Dupont/i }).click();
    await page.getByRole("button", { name: /^Inviter$/i }).click();
    await expect.poll(() => inviteCalled).toBe(true);
    await expect(page.getByRole("button", { name: /Invitation envoyée/i })).toBeVisible();
  });

  test("les suggestions à suivre sont repliées, chargées au clic, et suivies via l’API existante", async ({
    page,
  }) => {
    const counter = { calls: 0 };
    let followBody: Record<string, unknown> | null = null;
    await mockFollowSuggestions(page, FOLLOW_SUGGESTIONS, counter);
    await page.route("**/me/followed-influencers", (route) => {
      if (route.request().method() === "POST") {
        followBody = JSON.parse(route.request().postData() || "{}");
        return route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ id: "follow-1", handle: "marie-coach", platform: "linkedin" }),
        });
      }
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ followed: [], cap: 5 }),
      });
    });

    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });

    // 1. La vue simplifiée reste épurée : le rail « À suivre » ne revient PAS…
    await expect(page.getByRole("region", { name: "À suivre" })).toHaveCount(0);
    // …et rien n'est affiché tant qu'on n'a pas cliqué.
    const toggle = page.getByRole("button", { name: "Profils à suivre" });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByText("Marie Coach")).toHaveCount(0);

    // 2. ⚠️ Chargement PARESSEUX : aucun appel serveur avant le dépliage. Sans
    //    ce garde, l'écran d'accueil paierait la requête tous les jours pour un
    //    panneau que peu de gens ouvrent — le gaspillage qu'on cherche à éviter.
    expect(counter.calls).toBe(0);

    // 3. Au clic, les suggestions arrivent, avec le motif du match.
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByText("Marie Coach")).toBeVisible();
    await expect(page.getByText(/correspond à ta niche : coaching · indépendants/i)).toBeVisible();
    await expect.poll(() => counter.calls).toBe(1);

    // 4. « Suivre » passe par l'endpoint existant (et son plafond de 5).
    await page.getByRole("button", { name: "Suivre Marie Coach" }).click();
    await expect.poll(() => followBody).not.toBeNull();
    expect(followBody).toMatchObject({ handle: "marie-coach" });
    await expect(page.getByRole("button", { name: "Suivre Marie Coach" })).toContainText("Suivi");

    // 5. Refermer puis rouvrir ne rappelle pas le serveur (une fois par écran).
    await toggle.click();
    await toggle.click();
    await expect(page.getByText("Marie Coach")).toBeVisible();
    expect(counter.calls).toBe(1);
  });

  test("profil éditorial vide : le panneau existe mais explique quoi faire", async ({ page }) => {
    const counter = { calls: 0 };
    await mockFollowSuggestions(page, [], counter);

    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });
    await page.getByRole("button", { name: "Profils à suivre" }).click();
    // Pas de liste vide muette : on dit pourquoi et quoi faire.
    await expect(page.getByText(/complète ton profil éditorial/i)).toBeVisible();
  });
});
