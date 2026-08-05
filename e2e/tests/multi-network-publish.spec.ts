import { test, expect, Page } from "@playwright/test";
import { gotoTab, gotoSubTab } from "./helpers";

// ALE-59 : publication multi-réseaux (X + Reddit). Depuis le retrait de
// « Publier maintenant sur LinkedIn » du menu Publier (2026-07-24), la rangée
// de logos multi-réseaux ne vit plus que dans la modale « Programmer… ».
//
// Tout le backend est MOCKÉ (statuts, adaptation IA, programmation) : zéro coût,
// rien ne part nulle part. Ce que ce spec verrouille, c'est le CÂBLAGE :
//
//  1. cliquer un logo appelle l'adaptation IA et empile la version ÉDITABLE
//     sous le post LinkedIn (pas d'onglets) ;
//  2. à la confirmation, les versions X et Reddit voyagent avec le post
//     (cross_posts dans le payload de /me/linkedin/schedule) avec les bons
//     champs (tweets[], subreddit/title/body) — une version perdue en route
//     publierait LinkedIn seul en silence, l'inverse exact de la promesse du
//     bouton « Programmer sur 3 réseaux » ;
//  3. compte non connecté à X → le logo n'active rien et explique quoi faire.

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
      selfpromo_tolerance: 1, min_karma_advised: 200, geo_score: 5,
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

/** Ouvre la modale Programmer sur le post mocké de Ma bibliothèque — c'est elle
 *  qui porte la rangée de logos multi-réseaux (pour un compte flaggé seulement). */
async function openScheduleModal(page: Page, { expectPanels = true } = {}) {
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Ma bibliothèque");
  await page.getByRole("button", { name: /Ouvrir « Post LinkedIn de test ALE-59/ }).click();
  const bar = page.locator(".post-actions-bar").first();
  await bar.getByRole("button", { name: /Publier/ }).click();
  // La publication LinkedIn immédiate est retirée du menu (elle reviendra).
  await expect(page.locator(".action-menu").getByRole("menuitem", { name: /Publier maintenant sur LinkedIn/ })).toHaveCount(0);
  await page.locator(".action-menu").getByRole("menuitem", { name: /Programmer/ }).click();
  if (expectPanels) await expect(page.getByTestId("cross-network-panels")).toBeVisible();
  else await expect(page.getByRole("button", { name: /Programmer sur LinkedIn/ })).toBeVisible();
}

test("programmer sur 3 réseaux : adaptation empilée, puis les versions X/Reddit voyagent dans cross_posts", async ({ page }) => {
  await mockBase(page);

  let schedulePayload: any = null;
  await page.route("**/me/linkedin/schedule", (route) => {
    schedulePayload = route.request().postDataJSON();
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ok: true, scheduled_post: { id: "sp-3" } }),
    });
  });

  await page.goto("/");
  await openScheduleModal(page);

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
  // Score GEO (export Readyt) → badge « Bien cité par les IA » sur les subs à haut GEO.
  await expect(redditPanel.getByText(/Bien cité par les IA/)).toBeVisible();

  // Le bouton dit ce qu'il va faire, et le fait : les deux versions voyagent
  // avec le post programmé.
  await page.getByRole("button", { name: "Programmer sur 3 réseaux" }).click();
  await expect.poll(() => schedulePayload).not.toBeNull();
  expect(schedulePayload.cross_posts?.x?.tweets).toEqual(X_ADAPTATION.tweets);
  expect(schedulePayload.cross_posts?.reddit?.subreddit).toBe("marketing");
  expect(schedulePayload.cross_posts?.reddit?.title).toBe(REDDIT_ADAPTATION.title);
  expect(schedulePayload.cross_posts?.reddit?.body).toBe(REDDIT_ADAPTATION.body);
  // Aucune erreur affichée après la programmation.
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
  await openScheduleModal(page, { expectPanels: false });
  await expect(page.getByTestId("cross-network-panels")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Publier aussi sur X" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Programmer sur LinkedIn/ })).toBeVisible();
});

test("sidebar : aucune entrée X/Reddit, même avec les flags ; Instagram dégrisé et dépliable", async ({ page }) => {
  await mockBase(page);
  await page.goto("/");
  // X et Reddit n'ont PAS d'entrée réseau, flags ou pas : leur publication
  // passe par la pop-up multi-réseaux et Mon profil › Connexions. Un teaser
  // « Bientôt » laisserait croire que la fonctionnalité n'existe pas encore.
  await expect(page.getByRole("button", { name: "X Bientôt" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Reddit Bientôt" })).toHaveCount(0);
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

test("programmer sans LinkedIn : X et Reddit seuls dans cross_posts avec skip_linkedin", async ({ page }) => {
  await mockBase(page);

  let schedulePayload: any = null;
  await page.route("**/me/linkedin/schedule", (route) => {
    schedulePayload = route.request().postDataJSON();
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ok: true, scheduled_post: { id: "sp-x-rd" } }),
    });
  });

  await page.goto("/");
  await openScheduleModal(page);

  // Désactiver LinkedIn (doit activer X ou Reddit d'abord — on active les deux).
  await page.getByRole("button", { name: "Publier aussi sur X" }).click();
  await expect(page.getByTestId("x-panel")).toBeVisible();
  await page.getByRole("button", { name: "Publier aussi sur Reddit" }).click();
  await expect(page.getByTestId("reddit-panel")).toBeVisible();
  await page.getByRole("button", { name: "Publier sur LinkedIn" }).click();
  await expect(page.getByText(/LinkedIn désactivé/)).toBeVisible();

  await page.getByRole("button", { name: /Programmer sur 2 réseau/ }).click();
  await expect.poll(() => schedulePayload).not.toBeNull();
  expect(schedulePayload.cross_posts?.skip_linkedin).toBe(true);
  expect(schedulePayload.cross_posts?.x?.tweets).toEqual(X_ADAPTATION.tweets);
  expect(schedulePayload.cross_posts?.reddit?.subreddit).toBe("marketing");
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
  await openScheduleModal(page);
  await page.getByRole("button", { name: "Publier aussi sur X" }).click();
  await expect(page.getByText(/Connecte ton compte X dans Mon profil/)).toBeVisible();
  await expect(page.getByTestId("x-panel")).toHaveCount(0);
  expect(adaptCalled).toBe(false);
  // Le bouton de confirmation reste « LinkedIn seul ».
  await expect(page.getByRole("button", { name: /Programmer sur LinkedIn/ })).toBeVisible();
});

// ── Texte éditable dans la modale Programmer ────────────────────────────────
// Le texte y était en LECTURE SEULE : depuis l'Agent IA, la réponse complète du
// modèle (explications comprises) partait telle quelle en programmation, sans
// aucun moyen de la retoucher — et le post partait des jours plus tard, blabla
// inclus. `PublishConfirmModal` était éditable depuis ALE-210 ; la modale
// Programmer était le trou restant. Ce spec verrouille les deux propriétés qui
// comptent : on peut corriger, et c'est bien la correction qui part au serveur.

test("programmer : le texte est éditable et c'est la version corrigée qui part", async ({ page }) => {
  await mockBase(page);

  let schedulePayload: any = null;
  await page.route("**/me/linkedin/schedule", (route) => {
    schedulePayload = route.request().postDataJSON();
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ok: true, scheduled_post: { id: "sp-edit" } }),
    });
  });

  await page.goto("/");
  await openScheduleModal(page);

  const textarea = page.getByTestId("schedule-post-text");
  await expect(textarea).toHaveValue(SAVED_POST.post);
  await expect(textarea).toBeEditable();

  const corrected = "Version corrigée : sans le blabla de l'agent.";
  await textarea.fill(corrected);

  await page.getByRole("button", { name: /Programmer sur LinkedIn/ }).click();
  await expect.poll(() => schedulePayload).not.toBeNull();
  // Le point du correctif : c'est la version corrigée qui est programmée.
  expect(schedulePayload.content).toBe(corrected);
  expect(schedulePayload.content).not.toContain(SAVED_POST.post);
});

test("programmer : un texte vidé ne peut pas être programmé", async ({ page }) => {
  // Sans ce garde-fou, effacer le blabla « un peu trop » programmerait un post
  // vide, découvert seulement au créneau de publication.
  await mockBase(page);
  await page.goto("/");
  await openScheduleModal(page);

  await page.getByTestId("schedule-post-text").fill("   ");
  await expect(page.getByRole("button", { name: /Programmer sur LinkedIn/ })).toBeDisabled();
});

test("programmer : l'adaptation X part du texte corrigé, pas de l'original", async ({ page }) => {
  // Si l'adaptation repartait du texte d'origine, le client verrait sa version
  // X reconstruite à partir du brouillon qu'il vient justement de nettoyer.
  await mockBase(page);

  let adaptPayload: any = null;
  await page.route("**/me/publish/adapt/x", (route) => {
    adaptPayload = route.request().postDataJSON();
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(X_ADAPTATION) });
  });

  await page.goto("/");
  await openScheduleModal(page);

  const corrected = "Texte nettoyé avant adaptation X.";
  await page.getByTestId("schedule-post-text").fill(corrected);
  await page.getByRole("button", { name: "Publier aussi sur X" }).click();

  await expect.poll(() => adaptPayload).not.toBeNull();
  expect(adaptPayload.content).toBe(corrected);
});
