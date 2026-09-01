import { test, expect, type Page } from "@playwright/test";
import { gotoTab, gotoSubTab } from "./helpers";

// Suggestions de profils LinkedIn à suivre (matching niche/ICP).
//
// Backend entièrement MOCKÉ : aucune analyse, aucun scrape, aucun crédit.
// Le spec verrouille les deux comportements qui, s'ils régressaient, ne
// lèveraient AUCUNE erreur visible :
//
//  1. le handle suggéré doit partir tel quel à `POST /me/followed-influencers`
//     — un handle abîmé en route fait suivre quelqu'un d'autre (ou personne),
//     et le cron de veille scrape alors le mauvais profil pendant des jours ;
//  2. une liste vide (profil éditorial pas encore rempli) doit faire
//     DISPARAÎTRE la section. Une section vide « Influenceurs suggérés » sur un
//     compte neuf donne l'impression d'un écran cassé, et c'est justement la
//     garantie produit : rien plutôt que des profils au hasard.

const SUGGESTIONS = [
  {
    handle: "marie-coach",
    name: "Marie Coach",
    headline: "Coaching business pour indépendants",
    profile_url: "https://www.linkedin.com/in/marie-coach/",
    follower_count: 5200,
    matched_keywords: ["coaching", "indépendants"],
  },
  {
    handle: "leo-consult",
    name: "Léo Consult",
    headline: "Consultant acquisition B2B",
    profile_url: "https://www.linkedin.com/in/leo-consult/",
    follower_count: 900,
    matched_keywords: ["consultant"],
  },
];

async function mockScreen(page: Page, suggestions: unknown[]) {
  // Compte fraîchement inscrit : aucun profil analysé, donc le classement est
  // vide — c'est exactement le cas où la section de suggestions sert.
  await page.route("**/me/influencers", (route) =>
    route.fulfill({ contentType: "application/json", body: "[]" })
  );
  await page.route("**/me/analyses**", (route) =>
    route.fulfill({ contentType: "application/json", body: "[]" })
  );
  await page.route("**/me/followed-influencers", (route) => {
    if (route.request().method() === "POST") {
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
  await page.route("**/me/follow-suggestions", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ suggestions, followed_count: 0, cap: 5 }),
    })
  );
}

test.beforeEach(async ({ page }) => {
  // Le Mode Pilote est l'écran par défaut : ce spec vit dans la vue Expert.
  await page.addInitScript(() => {
    localStorage.setItem("lkd_interface_mode", "expert");
  });
});

test("suggestions affichées avec le motif du match, et suivi via l'endpoint existant", async ({ page }) => {
  let followBody: Record<string, unknown> | null = null;
  await mockScreen(page, SUGGESTIONS);
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().includes("/me/followed-influencers")) {
      followBody = JSON.parse(req.postData() || "{}");
    }
  });

  await page.goto("/");
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Analyses");

  const card = page.locator(".card", { hasText: "Influenceurs suggérés à suivre" });
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card.getByText("Marie Coach")).toBeVisible();
  await expect(card.getByText("Coaching business pour indépendants")).toBeVisible();
  // Le « pourquoi » de la suggestion : sans lui, la liste ressemble à une pub.
  await expect(card.getByText(/Correspond à ta niche\s*:\s*coaching · indépendants/)).toBeVisible();
  await expect(card.getByText("Léo Consult")).toBeVisible();

  // Le lien pointe bien vers le profil LinkedIn suggéré.
  await expect(card.getByRole("link", { name: "Marie Coach" })).toHaveAttribute(
    "href",
    "https://www.linkedin.com/in/marie-coach/",
  );

  await card.getByRole("button", { name: "Suivre Marie Coach" }).click();

  // Le handle part intact — c'est lui que le cron de veille scrapera ensuite.
  await expect.poll(() => followBody).not.toBeNull();
  expect(followBody).toMatchObject({ handle: "marie-coach" });

  // Une fois suivi, le profil quitte la liste des suggestions (il est désormais
  // dans la veille : le reproposer serait un doublon).
  await expect(card.getByText("Marie Coach")).toHaveCount(0);
  await expect(card.getByText("Léo Consult")).toBeVisible();
});

test("profil éditorial vide : aucune suggestion, aucune section", async ({ page }) => {
  await mockScreen(page, []);

  await page.goto("/");
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Analyses");

  // Le reste de l'écran est bien chargé…
  await expect(page.getByRole("heading", { name: /^Mes influenceurs$/i })).toBeVisible({ timeout: 30_000 });
  // …mais la section de suggestions n'existe pas du tout.
  await expect(page.getByText("Influenceurs suggérés à suivre")).toHaveCount(0);
  await expect(page.locator(".error")).toHaveCount(0);
});
