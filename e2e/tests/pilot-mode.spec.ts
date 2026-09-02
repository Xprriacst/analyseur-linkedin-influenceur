import { test, expect } from "@playwright/test";

// Mode Pilote — câblage réel (backend mocké, 0 Anthropic / 0 Apify).
// Vérifie : atterrissage Pilote, toggle Pilote/Expert, agent IA
// prospects, invite → file outreach, et stratégie + influenceurs à suivre dans
// « Mon profil » (plus dans la vue du jour).

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
    prospect_agent: {
      active: false,
      status: "idle",
      message: "",
      detail: null,
    },
    is_pilote_landing: true,
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
  await page.route("**/me/billing", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ enabled: true, subscribed: false, plan: { amount: 49, credits: 1000 } }),
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

  test("un compte agence atterrit sur le Mode Pilote avec nav simplifiée", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });
    await expect(page.getByRole("heading", { name: /Post du jour/i })).toBeVisible();
    await expect(page.locator(".sidebar")).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Navigation Mode Pilote" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Vue pilote/i })).toBeVisible();
    const modeToggle = page.getByRole("tablist", { name: "Mode d'interface" });
    await expect(modeToggle).toBeVisible();
    await expect(modeToggle.getByRole("tab", { name: "Pilote" })).toHaveAttribute("aria-selected", "true");
    await expect(modeToggle.getByRole("tab", { name: "Expert" })).toHaveAttribute("aria-selected", "false");
  });

  test("le toggle Expert ouvre l'aperçu lecture seule (tier gratuit)", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });
    await page.getByRole("tab", { name: "Expert" }).click();
    await expect(page.getByRole("heading", { name: /Tu vois l'interface complète, en lecture seule/i })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.locator(".app-shell.pilot-expert-preview-active")).toBeVisible();
    await expect(page.locator(".sidebar")).toBeVisible();
  });

  test("tier gratuit : Publier, Modifier et Autre angle sont grisés", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });
    await expect(page.getByRole("button", { name: /^Publier$/i })).toBeDisabled({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: /^Modifier$/i })).toBeDisabled();
    await expect(page.getByRole("button", { name: /^Autre angle$/i })).toBeDisabled();
  });

  test("sans simulation, pas de carte agent IA fictive", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });
    await expect(page.getByText(/Agent IA en recherche/i)).toHaveCount(0);
  });

  test("la vue du jour ne porte plus stratégie ni influenceurs à suivre", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });
    // Elles ont déménagé dans « Mon profil » : la vue du jour ne garde que ce
    // qu'il y a à faire aujourd'hui (le post, les gens à contacter).
    await expect(page.getByRole("button", { name: "Influenceurs à suivre" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Ta stratégie" })).toHaveCount(0);
  });

  test("tier gratuit : Inviter est grisé", async ({ page }) => {
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
    await page.getByRole("button", { name: /Camille Dupont/i }).click();
    const inviteBtn = page.getByRole("button", { name: /^Inviter$/i });
    await expect(inviteBtn).toBeDisabled({ timeout: 15_000 });
    await inviteBtn.click({ force: true });
    expect(inviteCalled).toBe(false);
  });

  test("Inviter appelle l’API outreach existante quand l’abonnement est actif", async ({ page }) => {
    await page.route("**/me/billing", (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ enabled: true, subscribed: true, plan: { amount: 49, credits: 1000 } }),
      }),
    );
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

  test("les suggestions à suivre vivent dans Mon profil, chargées à l’ouverture, et suivies via l’API existante", async ({
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

    // 1. La vue du jour reste épurée : ni rail « À suivre », ni suggestions.
    await expect(page.getByRole("region", { name: "À suivre" })).toHaveCount(0);
    await expect(page.getByText("Marie Coach")).toHaveCount(0);

    // 2. ⚠️ Chargement PARESSEUX : aucun appel serveur tant qu'on est sur la vue
    //    du jour. Sans ce garde, l'écran d'accueil relirait le cache mutualisé
    //    tous les jours, pour tout le monde — le gaspillage qu'on évite.
    expect(counter.calls).toBe(0);

    // 3. Elles vivent dans « Mon profil », chargées à l'ouverture de l'onglet.
    await page.getByRole("button", { name: /Mon profil/i }).click();
    await expect(page.getByText("Marie Coach")).toBeVisible();
    await expect(page.getByText(/correspond à ta niche : coaching · indépendants/i)).toBeVisible();
    await expect.poll(() => counter.calls).toBe(1);

    // 4. « Suivre » passe par l'endpoint existant (et son plafond de 5).
    await page.getByRole("button", { name: "Suivre Marie Coach" }).click();
    await expect.poll(() => followBody).not.toBeNull();
    expect(followBody).toMatchObject({ handle: "marie-coach" });
    await expect(page.getByRole("button", { name: "Suivre Marie Coach" })).toContainText("Suivi");

    // 5. Aller-retour entre les deux onglets : une seule requête par session.
    await page.getByRole("button", { name: /Vue pilote/i }).click();
    await page.getByRole("button", { name: /Mon profil/i }).click();
    await expect(page.getByText("Marie Coach")).toBeVisible();
    expect(counter.calls).toBe(1);
  });

  test("Mon profil affiche la stratégie du plan", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });
    await page.getByRole("button", { name: /Mon profil/i }).click();
    await expect(page.getByRole("heading", { name: "Ta stratégie" })).toBeVisible();
    await expect(page.getByText("Fondateurs SaaS · outbound assisté")).toBeVisible();
    await expect(page.getByText("3 posts / semaine · lun 9h, mer 9h")).toBeVisible();
  });

  test("Mon profil permet de se déconnecter", async ({ page }) => {
    // ⚠️ Le Mode Pilote n'a pas d'entête d'application : sans cette ligne, un
    // client n'a AUCUN moyen de sortir de son compte.
    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });
    await page.getByRole("button", { name: /Mon profil/i }).click();
    await expect(page.getByRole("heading", { name: "Ton compte" })).toBeVisible();
    await page.getByRole("button", { name: /Se déconnecter/i }).click();
    // Retour sur la landing publique : plus de navigation Pilote.
    await expect(page.getByRole("navigation", { name: "Navigation Mode Pilote" })).toHaveCount(0);
  });

  test("profil éditorial vide : le panneau existe mais explique quoi faire", async ({ page }) => {
    const counter = { calls: 0 };
    await mockFollowSuggestions(page, [], counter);

    await expect(page.getByRole("heading", { name: /Bonjour Alex\./i })).toBeVisible({
      timeout: 45_000,
    });
    await page.getByRole("button", { name: /Mon profil/i }).click();
    // Pas de liste vide muette : on dit pourquoi et quoi faire.
    await expect(page.getByText(/complète ton profil éditorial/i)).toBeVisible();
  });
});
