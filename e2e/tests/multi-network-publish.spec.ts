import { test, expect, Page } from "@playwright/test";
import { gotoTab, gotoSubTab } from "./helpers";

// ALE-59 : pop-up de publication multi-réseaux (X + Reddit).
//
// Tout le backend est MOCKÉ (statuts, adaptation IA, publications) : zéro coût,
// rien ne part nulle part. Ce que ce spec verrouille, c'est le CÂBLAGE :
//
//  1. cliquer un logo appelle l'adaptation IA et empile la version ÉDITABLE
//     sous le post LinkedIn (pas d'onglets) ;
//  2. à la confirmation, les versions X et Reddit partent au serveur avec les
//     bons champs (tweets[], subreddit/title/body) — une version perdue en
//     route publierait LinkedIn seul en silence, l'inverse exact de la promesse
//     du bouton « Publier sur 3 réseaux » ;
//  3. la même mécanique dans Programmer stocke les versions avec le post
//     (cross_posts dans le payload de /me/linkedin/schedule) ;
//  4. compte non connecté à X → le logo n'active rien et explique quoi faire.

const SAVED_POST = {
  id: "e2e-ale-59",
  post: "Post LinkedIn de test ALE-59 : la régularité bat le volume.",
  topic: "Sujet test",
  created_at: "2026-07-01T10:00:00Z",
  media_items: [],
};

const X_ADAPTATION = { tweets: ["Version X adaptée : la régularité bat le volume."], text: "Version X adaptée : la régularité bat le volume." };

const REDDIT_ADAPTATION = {
  title: "I analyzed consistency vs volume on LinkedIn",
  body: "Adapted Reddit body with real numbers.",
  suggestions: [
    {
      name: "marketing", reason: "cœur de cible", in_library: true,
      selfpromo_tolerance: 1, min_karma_advised: 200,
      notes: "Autopromo bannie.", exists: true, subscribers: 1500000,
    },
    { name: "B2BMarketing", reason: "niche B2B", in_library: true, selfpromo_tolerance: 2, min_karma_advised: 100, exists: true, subscribers: 90000 },
  ],
};

/** Mocks communs : un post sauvegardé + tous les réseaux connectés.
 *  Les feature flags viennent du serveur (déploiement progressif) : par défaut
 *  on mocke un compte flaggé ; `features: []` simule un compte non concerné. */
async function mockBase(page: Page, { xConnected = true, redditConnected = true, features = ["instagram", "x", "reddit"] as string[] } = {}) {
  await page.route("**/me/features", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ features }) })
  );
  await page.route("**/me/generated-posts", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({ contentType: "application/json", body: JSON.stringify([SAVED_POST]) });
    }
    return route.fallback();
  });
  await page.route("**/me/linkedin/status", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ configured: true, connected: true, account_id: "li-1" }) })
  );
  await page.route("**/me/x/status", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ configured: true, connected: xConnected }) })
  );
  await page.route("**/me/reddit/status", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ configured: true, connected: redditConnected }) })
  );
  await page.route("**/me/publish/adapt/x", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(X_ADAPTATION) })
  );
  await page.route("**/me/publish/adapt/reddit", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(REDDIT_ADAPTATION) })
  );
}

/** Ouvre la pop-up Publier sur le post mocké de Ma bibliothèque. */
async function openPublishModal(page: Page, { expectPanels = true } = {}) {
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Ma bibliothèque");
  await page.getByRole("button", { name: /Ouvrir « Post LinkedIn de test ALE-59/ }).click();
  const bar = page.locator(".post-actions-bar").first();
  await bar.getByRole("button", { name: /Publier/ }).click();
  await page.locator(".action-menu").getByRole("menuitem", { name: /Publier maintenant sur LinkedIn/ }).click();
  // La pop-up de confirmation porte la rangée de logos multi-réseaux — pour un
  // compte flaggé seulement.
  if (expectPanels) await expect(page.getByTestId("cross-network-panels")).toBeVisible();
  else await expect(page.getByRole("button", { name: /Confirmer la publication/ })).toBeVisible();
}

test("publier sur 3 réseaux : adaptation empilée, puis les 3 versions partent au serveur", async ({ page }) => {
  await mockBase(page);

  const published: Record<string, unknown> = {};
  await page.route("**/me/linkedin/publish", (route) => {
    published.linkedin = route.request().postDataJSON();
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: true, post_id: "z-li" }) });
  });
  await page.route("**/me/x/publish", (route) => {
    published.x = route.request().postDataJSON();
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: true, post_id: "z-x" }) });
  });
  await page.route("**/me/reddit/publish", (route) => {
    published.reddit = route.request().postDataJSON();
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: true, post_id: "z-rd" }) });
  });

  await page.goto("/");
  await openPublishModal(page);

  // Activer X : la version adaptée apparaît, empilée, éditable, avec compteur.
  await page.getByRole("button", { name: "Publier aussi sur X" }).click();
  const xPanel = page.getByTestId("x-panel");
  await expect(xPanel.getByLabel("Version X du post")).toHaveValue(X_ADAPTATION.tweets[0]);
  await expect(xPanel.getByText(/280/).first()).toBeVisible();

  // Activer Reddit : titre + subreddit suggéré + badges d'avertissement.
  await page.getByRole("button", { name: "Publier aussi sur Reddit" }).click();
  const redditPanel = page.getByTestId("reddit-panel");
  await expect(redditPanel.getByLabel("Titre du post Reddit")).toHaveValue(REDDIT_ADAPTATION.title);
  await expect(redditPanel.getByLabel("Subreddit")).toHaveValue("marketing");
  await expect(redditPanel.getByText(/Autopromo mal vue/)).toBeVisible();
  await expect(redditPanel.getByText(/Karma min\. conseillé : 200/)).toBeVisible();

  // Le bouton dit ce qu'il va faire, et le fait.
  await page.getByRole("button", { name: "Publier sur 3 réseaux" }).click();
  await expect.poll(() => Object.keys(published).sort()).toEqual(["linkedin", "reddit", "x"]);

  const xPayload = published.x as { tweets: string[] };
  expect(xPayload.tweets).toEqual(X_ADAPTATION.tweets);
  const redditPayload = published.reddit as { subreddit: string; title: string; body: string };
  expect(redditPayload.subreddit).toBe("marketing");
  expect(redditPayload.title).toBe(REDDIT_ADAPTATION.title);
  expect(redditPayload.body).toBe(REDDIT_ADAPTATION.body);
  // Aucune erreur affichée après la triple publication.
  await expect(page.locator(".error")).toHaveCount(0);
});

test("programmer : les versions X/Reddit voyagent dans cross_posts avec le post", async ({ page }) => {
  await mockBase(page);

  let schedulePayload: any = null;
  await page.route("**/me/linkedin/schedule", (route) => {
    schedulePayload = route.request().postDataJSON();
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ok: true, scheduled_post: { id: "sp-1" } }),
    });
  });

  await page.goto("/");
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Ma bibliothèque");
  await page.getByRole("button", { name: /Ouvrir « Post LinkedIn de test ALE-59/ }).click();
  const bar = page.locator(".post-actions-bar").first();
  await bar.getByRole("button", { name: /Publier/ }).click();
  await page.locator(".action-menu").getByRole("menuitem", { name: /Programmer/ }).click();

  await expect(page.getByTestId("cross-network-panels")).toBeVisible();
  await page.getByRole("button", { name: "Publier aussi sur X" }).click();
  await expect(page.getByTestId("x-panel").getByLabel("Version X du post")).toHaveValue(X_ADAPTATION.tweets[0]);

  await page.getByRole("button", { name: /Programmer sur 2 réseaux/ }).click();
  await expect.poll(() => schedulePayload).not.toBeNull();
  expect(schedulePayload.cross_posts?.x?.tweets).toEqual(X_ADAPTATION.tweets);
  expect(schedulePayload.cross_posts?.reddit).toBeUndefined();
});

test("compte SANS flags : rien de multi-réseaux ne s'affiche (même état serveur)", async ({ page }) => {
  // Même post, mêmes statuts connectés — seul le flag change. Un compte non
  // concerné ne doit voir NI la rangée de logos dans la pop-up, NI les entrées
  // X/Reddit de la sidebar, et Instagram doit rester grisé « Bientôt ».
  await mockBase(page, { features: [] });
  await page.goto("/");
  await expect(page.locator(".nav-item", { hasText: "Instagram" }).first()).toBeDisabled();
  await expect(page.getByRole("button", { name: "X Bientôt" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Reddit Bientôt" })).toHaveCount(0);
  await openPublishModal(page, { expectPanels: false });
  await expect(page.getByTestId("cross-network-panels")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Publier aussi sur X" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Confirmer la publication/ })).toBeVisible();
});

test("sidebar : X et Reddit grisés « Bientôt », Instagram dégrisé et dépliable", async ({ page }) => {
  await mockBase(page);
  await page.goto("/");
  // X et Reddit : entêtes visibles mais inertes (la publication passe par la
  // pop-up multi-réseaux ; l'onglet réseau dédié reste à construire).
  await expect(page.getByRole("button", { name: "X Bientôt" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Reddit Bientôt" })).toBeDisabled();
  // Instagram n'est plus grisé : son entête se déplie et révèle son sous-onglet
  // Contenu (en plus de celui de LinkedIn, ouvert par défaut).
  const contenu = page.locator(".nav-item-sub", { hasText: "Contenu" });
  const before = await contenu.count();
  await page.locator(".nav-item", { hasText: "Instagram" }).first().click();
  await expect(contenu).toHaveCount(before + 1);
  // Sous Instagram déplié : la Prospection IG n'existe pas encore — teaser
  // grisé « Bientôt », inerte.
  await expect(page.getByRole("button", { name: "Prospection Bientôt" })).toBeDisabled();
  await expect(page.locator(".error")).toHaveCount(0);
});

test("compte X non connecté : le logo n'active rien et renvoie vers Connexions", async ({ page }) => {
  await mockBase(page, { xConnected: false });
  let adaptCalled = false;
  await page.route("**/me/publish/adapt/x", (route) => {
    adaptCalled = true;
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(X_ADAPTATION) });
  });

  await page.goto("/");
  await openPublishModal(page);
  await page.getByRole("button", { name: "Publier aussi sur X" }).click();
  await expect(page.getByText(/Connecte ton compte X dans Mon profil/)).toBeVisible();
  await expect(page.getByTestId("x-panel")).toHaveCount(0);
  expect(adaptCalled).toBe(false);
  // Le bouton de confirmation reste « LinkedIn seul ».
  await expect(page.getByRole("button", { name: /Confirmer la publication/ })).toBeVisible();
});
