import { test, expect, Page } from "@playwright/test";
import { gotoTab } from "./helpers";

/**
 * Mon profil → Tableau de bord (backlog Notion, priorité Alex 2026-08-31).
 *
 * LECTURE SEULE et backend MOCKÉ : aucune génération, aucun scrape, aucun appel
 * Unipile réel → zéro coût Anthropic/Apify/Unipile.
 *
 * Ce que ces specs verrouillent, et pourquoi :
 *  - le chiffre d'abonnés N'EST PAS un 0 quand rien n'a été mesuré (un « 0 abonné »
 *    affiché comme un fait sur son propre compte est exactement la panne que ce
 *    tableau de bord doit éviter — elle ne lève aucune erreur) ;
 *  - un échantillon borné est annoncé comme tel (sinon « 3 réponses » se lit comme
 *    un total alors qu'on n'a regardé que 20 conversations sur 200) ;
 *  - sans compte LinkedIn relié, la sonde Unipile n'est JAMAIS lancée ;
 *  - l'onglet par défaut de « Mon profil » reste le contexte éditorial.
 */

const PROGRESS_WITH_HISTORY = {
  followers: {
    available: true,
    current: 1350,
    current_at: "2026-08-30",
    baseline: 1200,
    baseline_at: "2026-07-01",
    delta: 150,
    history: [
      { date: "2026-07-01", followers: 1200 },
      { date: "2026-08-01", followers: 1280 },
      { date: "2026-08-30", followers: 1350 },
    ],
  },
  invitations: { sent_today: 4, sent_week: 27, total_invited: 212, total_connected: 63 },
  messages: { sent_today: 2, total_sent: 48 },
  counts_reliable: true,
  unipile_connected: true,
};

async function mockDashboard(
  page: Page,
  progress: Record<string, unknown>,
  replies?: Record<string, unknown>,
) {
  await page.addInitScript(() => {
    localStorage.setItem("lkd_interface_mode", "expert");
  });
  await page.route("**/me/dashboard/progress", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ contentType: "application/json", body: JSON.stringify(progress) })
      : route.fallback(),
  );
  await page.route("**/me/dashboard/replies", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(
            replies ?? {
              conversations: { available: true, total: 31 },
              replies: { available: true, replied: 7, checked: 20, total_messaged: 48, capped: true },
            },
          ),
        })
      : route.fallback(),
  );
}

async function openDashboard(page: Page) {
  await page.goto("/");
  await gotoTab(page, "Mon profil");
  await page.locator(".tab", { hasText: "Tableau de bord" }).click();
  await expect(page.getByTestId("profile-dashboard")).toBeVisible({ timeout: 60_000 });
}

test("Tableau de bord : abonnés, progression depuis la baseline et courbe", async ({ page }) => {
  await mockDashboard(page, PROGRESS_WITH_HISTORY);
  await openDashboard(page);

  await expect(page.getByTestId("dash-followers-current")).toHaveText(/1\s*350/);
  // Le delta et sa baseline : « où j'en suis » n'a de sens que par rapport à d'où
  // je pars — afficher le seul chiffre courant ne dirait rien d'une progression.
  await expect(page.getByTestId("dash-followers-delta")).toContainText("+150");
  await expect(page.getByTestId("dash-followers-delta")).toContainText("1 200");
  await expect(page.getByTestId("dash-follower-curve")).toBeVisible();

  await expect(page.getByText("Invitations aujourd'hui")).toBeVisible();
  await expect(page.getByText("Invitations acceptées")).toBeVisible();
  // Taux d'acceptation dérivé : 63 / 212 ≈ 30 %.
  await expect(page.getByText(/30 % des invités/)).toBeVisible();

  await expect(page.locator(".error")).toHaveCount(0);
});

test("Tableau de bord : sans profil analysé, on explique — jamais « 0 abonné »", async ({ page }) => {
  await mockDashboard(page, {
    ...PROGRESS_WITH_HISTORY,
    followers: { available: false, reason: "no_own_profile_analyzed" },
  });
  await openDashboard(page);

  await expect(page.getByText(/Pas encore de relevé/i)).toBeVisible();
  // ⚠️ Le cœur du test : aucun chiffre d'abonnés ne doit s'afficher. Un « 0 » ici
  // serait lu comme « ce compte n'a aucun abonné » alors qu'on n'a rien mesuré.
  await expect(page.getByTestId("dash-followers-current")).toHaveCount(0);
  await expect(page.getByTestId("dash-followers-delta")).toHaveCount(0);
  await expect(page.getByTestId("dash-follower-curve")).toHaveCount(0);
  await expect(page.locator(".error")).toHaveCount(0);
});

test("Tableau de bord : un échantillon borné est annoncé comme tel", async ({ page }) => {
  await mockDashboard(page, PROGRESS_WITH_HISTORY);
  await openDashboard(page);

  await expect(page.getByTestId("dash-conversations")).toContainText("31");
  const replies = page.getByTestId("dash-replies");
  await expect(replies).toContainText("7");
  await expect(replies).toContainText("20");
  // Sans cette mention, « 7 réponses » se lirait comme un total sur 48 prospects
  // contactés alors qu'on n'a vérifié que les 20 conversations les plus récentes.
  await expect(replies).toContainText(/Échantillon des plus récentes/i);
  await expect(replies).toContainText("48");
});

test("Tableau de bord : sans compte LinkedIn relié, aucune sonde Unipile n'est lancée", async ({ page }) => {
  let repliesCalls = 0;
  await page.route("**/me/dashboard/replies", (route) => {
    repliesCalls += 1;
    return route.fulfill({ contentType: "application/json", body: "{}" });
  });
  await mockDashboard(page, { ...PROGRESS_WITH_HISTORY, unipile_connected: false });
  await openDashboard(page);

  await expect(page.getByText(/Relie ton compte LinkedIn/i)).toBeVisible();
  await page.waitForTimeout(1500);
  // Vérifier les réponses coûte un appel Unipile PAR conversation : sans compte
  // relié il n'y a rien à interroger, et lancer la sonde quand même serait une
  // dépense pure — invisible à l'écran, donc jamais remarquée.
  expect(repliesCalls).toBe(0);
});

test("Tableau de bord : l'onglet par défaut de Mon profil reste le contexte éditorial", async ({ page }) => {
  await mockDashboard(page, PROGRESS_WITH_HISTORY);
  await page.goto("/");
  await gotoTab(page, "Mon profil");

  // Le tableau de bord est un onglet de PLUS, pas le nouvel écran d'entrée : « Mon
  // profil » reste ce qu'on vient remplir. (Une itération passée l'avait mis par
  // défaut et avait cassé les 3 specs du profil, cf. CLAUDE.md.)
  await expect(page.locator(".tab.active", { hasText: "Mon profil" })).toBeVisible();
  await expect(page.locator(".tab", { hasText: "Tableau de bord" })).toBeVisible();
  await expect(page.getByTestId("profile-dashboard")).toHaveCount(0);
});
