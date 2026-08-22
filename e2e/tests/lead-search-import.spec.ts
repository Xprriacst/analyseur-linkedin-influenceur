import { test, expect } from "@playwright/test";
import { gotoTab } from "./helpers";

// Import d'un lien de recherche LinkedIn comme source de leads (migration 0062).
//
// Backend entièrement MOCKÉ : ce spec ne déclenche aucune recherche LinkedIn et
// ne coûte rien. Il verrouille les deux pannes de cet écran qui seraient
// totalement silencieuses :
//
//  1. l'URL de recherche ET le volume choisi doivent partir au serveur. Perdre
//     l'un des deux en route donne un import qui ne correspond pas à ce que le
//     client a demandé (autre recherche, autre volume) sans la moindre erreur ;
//  2. à la fin du job, la liste de leads doit être RECHARGÉE. Sans ça, les
//     prospects sont bien en base mais l'écran reste vide — le client conclut
//     que l'import a échoué et le relance, sollicitant son compte LinkedIn pour rien.

const CONNECTED = {
  configured: true,
  connected: true,
  account_name: "Compte de test",
  quota: {
    daily_cap: 25, weekly_invite_cap: 100, invites_today: 0, messages_today: 0, invites_week: 0,
    can_invite: true, can_message: true, counts_available: true,
  },
};

const SEARCH_URL = "https://www.linkedin.com/search/results/people/?keywords=CTO%20SaaS";

const LEAD = {
  id: "lead-1",
  profile_url: "https://www.linkedin.com/in/camille-roy",
  name: "Camille Roy",
  headline: "CMO @ Acme",
  signal_count: 1,
  status: "new",
  // Un lead issu d'une recherche n'a PAS commenté : le libellé « a commenté »
  // (héritage des commentateurs) serait un mensonge d'affichage.
  signals: [{ post_url: SEARCH_URL }],
};

async function mockProspecting(
  page: import("@playwright/test").Page,
  opts: { connected?: boolean } = {},
) {
  const connected = opts.connected !== false;
  await page.route("**/me/features", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ features: [] }) })
  );
  await page.route("**/me/linkedin/outreach/status", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(connected ? CONNECTED : { configured: true, connected: false }),
    })
  );
  await page.route("**/me/lead-targeting", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ targeting: {} }) })
  );
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("l'URL et le volume choisis partent au serveur, et les leads arrivent à la fin du job", async ({ page }) => {
  await mockProspecting(page);

  // La liste est vide AVANT l'import, peuplée après : c'est ce qui prouve que
  // l'écran se recharge tout seul quand le job se termine.
  let jobDone = false;
  await page.route("**/me/leads", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ leads: jobDone ? [LEAD] : [] }),
    })
  );

  let sent: any = null;
  await page.route("**/me/lead-searches", async (route) => {
    sent = JSON.parse(route.request().postData() || "{}");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        source: { id: "src-1", post_url: sent.url, kind: "search" },
        job: { id: "job-1", source_id: "src-1", status: "queued", max_comments: sent.max_results, result: null, error: null },
        existing: false,
      }),
    });
  });

  await page.route("**/me/lead-collection-jobs/job-1", async (route) => {
    jobDone = true;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "job-1",
        source_id: "src-1",
        status: "done",
        max_comments: 200,
        result: { comments_count: 200, leads: { inserted: 180, updated: 20 }, credits: null },
        error: null,
      }),
    });
  });

  await gotoTab(page, "Prospection");
  await page.getByRole("button", { name: /Importer une recherche LinkedIn/i }).click();

  const searchUrl = SEARCH_URL;
  await page.getByRole("textbox", { name: /Lien de la recherche/i }).fill(searchUrl);
  // Curseur : on demande explicitement un volume différent du défaut (100).
  await page.getByRole("slider", { name: /Nombre de prospects/i }).fill("200");
  await page.getByRole("button", { name: /Importer les prospects/i }).click();

  await expect.poll(() => sent).not.toBeNull();
  expect(sent.url).toBe(searchUrl);
  expect(sent.max_results).toBe(200);

  // Fin du job : le compte-rendu s'affiche ET la liste se remplit sans action.
  await expect(page.getByText(/200 profils récupérés/i)).toBeVisible({ timeout: 15000 });
  await expect(page.getByText("Camille Roy")).toBeVisible();
  const row = page.getByRole("button", { name: /Camille Roy/ });
  await expect(row).toContainText("trouvé dans ta recherche");
  await expect(row).not.toContainText("a commenté");
});

test("sans compte LinkedIn connecté, aucun formulaire d'import n'est proposé", async ({ page }) => {
  // Fail closed : la recherche est lue depuis le compte du client. Proposer le
  // formulaire sans compte connecté ne produirait qu'une erreur serveur.
  await mockProspecting(page, { connected: false });
  await page.route("**/me/leads", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ leads: [] }) })
  );

  await gotoTab(page, "Prospection");
  await page.getByRole("button", { name: /Importer une recherche LinkedIn/i }).click();

  await expect(page.getByText(/Connecte d'abord ton compte LinkedIn/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /Importer les prospects/i })).toHaveCount(0);
});
