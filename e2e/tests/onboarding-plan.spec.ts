import { test, expect, type Page } from "@playwright/test";

/**
 * Fin de l'onboarding in-app : l'agent compose un plan (stratégie + comptes à
 * suivre) puis le client atterrit sur sa vue du jour.
 *
 * Backend entièrement mocké — 0 Anthropic, 0 Apify, 0 crédit.
 *
 * Ce spec verrouille trois pannes qui ne se voient PAS à l'écran :
 *
 * 1. Le profil doit être écrit AVANT que la stratégie soit lue. L'inverse
 *    afficherait la stratégie générique d'un compte vide — au moment précis où
 *    on promet au client qu'elle est faite pour lui. Rien ne le signalerait :
 *    l'écran serait plein, juste faux.
 * 2. L'écran de détail de l'analyse (accroche + hashtags + forts/à améliorer)
 *    ne fait plus partie de l'onboarding : un « Voir mon potentiel » qui
 *    reviendrait rallongerait le tunnel sans qu'aucun test ne tombe.
 * 3. La sortie se fait sur la VUE PILOTE, même si le navigateur garde
 *    « expert » d'un compte testé avant. Sans ce garde, un compte tout neuf
 *    atterrit sur l'interface complète que l'onboarding vient de ne pas lui
 *    promettre.
 */

const PREVIEW = {
  handle: "alex-test",
  name: "Alex Test",
  headline: "Fondateur · automatisation LinkedIn",
  avatar_url: "",
  posts_count: 12,
  followers: 1850,
  connections: 520,
  niche: "Automatisation LinkedIn pour fondateurs",
  summary: "Premier paragraphe.\n\nDeuxième paragraphe.",
  hook: "Tu parles de ton produit, jamais du problème.",
  hashtags: ["#SaaS"],
  strengths: ["Ton direct"],
  improvements: ["Headline floue"],
};

const PILOT_TODAY = {
  plan: {
    userName: "Alex",
    dayNumber: 1,
    weekNumber: 36,
    weeklyDone: 0,
    weeklyTotal: 3,
    author: { name: "Alex Test", headline: "Fondateur", initials: "AT" },
    post: { structure: "Récit", hook: "", body: "" },
    followProfiles: [],
    contacts: [],
    strategy: {
      profiles: [],
      frequency: "1 post par jour — ton agent l'écrit chaque matin",
      target: "Fondateurs SaaS",
      structureHint: "Direct",
    },
  },
  meta: {
    post_id: null,
    post_source: null,
    post_text: "",
    post_empty: true,
    media_items: [],
    follow_handles: {},
    linkedin_outreach_connected: false,
    linkedin_publish_connected: false,
    contacts_blocked_reason: null,
    prospect_agent: null,
    is_pilote_landing: true,
  },
};

/** Réouvre l'onboarding sur le compte de test (qui l'a déjà passé) en reposant
 *  le drapeau `onboarding_pending` dans la session stockée par le navigateur. */
async function reopenOnboarding(page: Page) {
  await page.addInitScript(() => {
    // ⚠️ Volontairement « expert » : la sortie doit quand même être la vue pilote.
    localStorage.setItem("lkd_interface_mode", "expert");
    for (const key of Object.keys(localStorage)) {
      if (!key.startsWith("sb-") || !key.includes("auth-token")) continue;
      try {
        const json = JSON.parse(localStorage.getItem(key) as string);
        if (!json?.user) continue;
        json.user.user_metadata = {
          ...(json.user.user_metadata || {}),
          onboarding_done: false,
          onboarding_pending: true,
        };
        localStorage.setItem(key, JSON.stringify(json));
      } catch {
        /* ignore */
      }
    }
  });
}

test.describe("Onboarding — plan final", () => {
  test("le profil est écrit avant la révélation, puis on atterrit sur la vue pilote", async ({
    page,
  }) => {
    // ⚠️ Le PUT répond en 1,5 s À DESSEIN : sans ce délai, la requête de
    // stratégie part de toute façon après (l'animation dure ~3,4 s) et le test
    // passerait même si l'écriture n'était plus attendue. C'est la COMPLÉTION
    // du profil qui doit précéder la lecture, pas son envoi.
    let saveDoneAt = 0;
    let strategyAt = 0;
    let savedProfile: Record<string, unknown> | null = null;
    let followBody: Record<string, unknown> | null = null;

    await page.route("**/me/profile", async (route) => {
      if (route.request().method() !== "PUT") {
        return route.fulfill({ contentType: "application/json", body: "{}" });
      }
      savedProfile = JSON.parse(route.request().postData() || "{}");
      await new Promise((r) => setTimeout(r, 1500));
      saveDoneAt = Date.now();
      return route.fulfill({ contentType: "application/json", body: "{}" });
    });
    await page.route("**/me/profile/draft", (route) =>
      route.fulfill({
        json: {
          profile: { display_name: "Alex Test", core_offer: "Automatisation" },
          preview: {
            ...PREVIEW,
            seo_audit: {
              score: 43,
              findings: [
                { key: "headline", label: "Titre du profil", ok: false, detail: "7 caractères" },
                { key: "banner", label: "Bannière", ok: true, detail: "personnalisée" },
              ],
              keywords: ["consultant seo", "audit linkedin"],
              priorities: ["Remplace « Founder » par ton métier réel"],
              banner_verdict: "Ta bannière est jolie mais ne dit pas ce que tu vends.",
              has_banner: true,
              banner_reviewed: true,
              banner_url: "",
            },
          },
        },
      }),
    );
    await page.route("**/me/pilot/strategy", (route) => {
      strategyAt = strategyAt || Date.now();
      return route.fulfill({
        json: {
          target: "Fondateurs SaaS · Automatisation LinkedIn",
          frequency: "1 post par jour — ton agent l'écrit chaque matin",
          structureHint: "Direct — objectif : générer des conversations",
        },
      });
    });
    await page.route("**/me/follow-suggestions", (route) =>
      route.fulfill({
        json: {
          suggestions: [
            {
              handle: "marie-coach",
              name: "Marie Coach",
              headline: "Coaching business pour indépendants",
              profile_url: "",
              follower_count: 5200,
              matched_keywords: ["coaching"],
            },
          ],
          followed_count: 0,
          cap: 5,
        },
      }),
    );
    await page.route("**/me/followed-influencers", (route) => {
      if (route.request().method() === "POST") {
        followBody = JSON.parse(route.request().postData() || "{}");
      }
      return route.fulfill({ json: { followed: [], cap: 5 } });
    });
    await page.route("**/me/pilot/today", (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(PILOT_TODAY) }),
    );

    await reopenOnboarding(page);
    await page.goto("/");

    // Même jeu de questions que /onboarding : un seul onboarding.
    await page.getByPlaceholder(/ton-site\.com/).fill("https://www.linkedin.com/in/alex-test/");
    await page.getByRole("button", { name: "Analyser" }).click();
    // Les 5 questions se posent PENDANT le chargement (2026-09-03) : plus
    // d'écran d'analyse séparé, plus de pages après.
    await expect(page.getByText("Pendant que ça tourne — question 1/5")).toBeVisible({ timeout: 30_000 });

    // (2) Le téléphone est le seul champ bloquant : tant qu'il est vide, on ne
    // passe pas. Vérifié par la négative — sans ça le « obligatoire » serait
    // décoratif.
    const suivant = page.getByRole("button", { name: /Continuer|Composer mon plan/ });
    await expect(suivant).toBeDisabled();
    await page.getByLabel("Téléphone").fill("06 12 34 56 78");
    await expect(suivant).toBeEnabled();

    for (let i = 0; i < 4; i++) await suivant.click();
    await page.getByRole("button", { name: "Composer mon plan" }).click();

    // (1) Le profil part AVANT la lecture de la stratégie.
    await expect(page.getByRole("heading", { name: /Ton plan est prêt/ })).toBeVisible({
      timeout: 20_000,
    });
    expect(saveDoneAt).toBeGreaterThan(0);
    expect(strategyAt).toBeGreaterThan(saveDoneAt);
    expect(savedProfile).toMatchObject({ display_name: "Alex Test", phone: "06 12 34 56 78" });

    // (4) L'audit du profil est rendu sur la MÊME page que la stratégie.
    await expect(page.getByText("Ton profil LinkedIn")).toBeVisible();
    await expect(page.getByText("43/100")).toBeVisible();
    await expect(page.getByText(/ne dit pas ce que tu vends/)).toBeVisible();
    await expect(page.getByText("consultant seo")).toBeVisible();

    // La stratégie affichée est bien celle lue sur le serveur.
    await expect(page.getByText("Fondateurs SaaS · Automatisation LinkedIn")).toBeVisible();
    await expect(page.getByText(/1 post par jour/)).toBeVisible();

    // « Suivre » passe par l'endpoint existant (et son plafond).
    await page.getByRole("button", { name: "Suivre Marie Coach" }).click();
    await expect.poll(() => followBody).not.toBeNull();
    expect(followBody).toMatchObject({ handle: "marie-coach" });

    // (3) Sortie = vue pilote, malgré le « expert » resté en localStorage.
    await page.getByRole("button", { name: /Voir ma vue du jour/ }).click();
    await expect(page.getByRole("navigation", { name: "Navigation Mode Pilote" })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.locator(".sidebar")).toHaveCount(0);
  });
});
