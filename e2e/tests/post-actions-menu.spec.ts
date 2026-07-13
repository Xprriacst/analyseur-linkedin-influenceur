import { test, expect, Page } from "@playwright/test";
import { gotoTab, gotoSubTab } from "./helpers";

// ALE-185 : barre d'actions unifiée sur les cartes de post — bouton « Publier ▴ »
// (menu vers le haut : LinkedIn / Programmer / Slack / X selon les réseaux
// connectés) + bouton « ⋯ » (actions secondaires). LECTURE SEULE : on ouvre les
// menus et on referme (Escape), sans jamais cliquer une action de publication.

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

/** Ouvre les deux menus de la première barre d'actions et vérifie leur contenu commun. */
async function checkActionsBar(page: Page, { expectDelete }: { expectDelete: boolean }) {
  const bar = page.locator(".post-actions-bar").first();
  await expect(bar).toBeVisible();

  // Menu principal « Publier » : publier maintenant + programmer, ouvert vers le haut.
  await bar.getByRole("button", { name: /Publier/ }).click();
  const menu = page.locator(".action-menu");
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: /Publier maintenant sur LinkedIn|Publié sur LinkedIn/ })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: /Programmer|Programmé/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);

  // Menu « ⋯ » : actions secondaires (le détail varie selon la section).
  await bar.getByRole("button", { name: "Plus d'actions" }).click();
  await expect(menu).toBeVisible();
  if (expectDelete) {
    await expect(menu.getByRole("menuitem", { name: /Supprimer/ })).toBeVisible();
  }
  // ALE-68 : la génération d'image IA est active (pop-up de prompt) — on vérifie
  // sa présence sans cliquer (le clic préparerait un prompt = appel LLM).
  await expect(menu.getByRole("menuitem", { name: /Générer une image IA/ })).toBeEnabled();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
}

test("Contenu › Mes contenus : menu Publier + ⋯ sur une carte de post (GET mocké)", async ({ page }) => {
  // Le compte de test n'a pas forcément de post sauvegardé et on ne peut pas en
  // générer (lecture seule) : on mocke le GET pour rendre une carte déterministe.
  await page.route("**/me/generated-posts", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify([
          { id: "e2e-ale-185", post: "Post de test ALE-185", topic: "Sujet test", created_at: "2026-07-01T10:00:00Z", media_items: [] },
        ]),
      });
    }
    return route.fallback();
  });
  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Ma bibliothèque");
  await expect(page.getByRole("heading", { name: /Mes contenus sauvegardés/i })).toBeVisible();
  await expect(page.locator(".error")).toHaveCount(0);
  await checkActionsBar(page, { expectDelete: true });

  // Le menu « ⋯ » de Mes contenus porte aussi : joindre des images + régénérer.
  const bar = page.locator(".post-actions-bar").first();
  await bar.getByRole("button", { name: "Plus d'actions" }).click();
  const menu = page.locator(".action-menu");
  await expect(menu.getByRole("menuitem", { name: /Joindre des images/ })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: /Régénérer sur ce sujet/ })).toBeVisible();
  // ALE-189 : retravailler avec l'Agent IA disponible aussi hors Générateur.
  await expect(menu.getByRole("menuitem", { name: /Retravailler avec l'Agent IA/ })).toBeVisible();
  // Clic hors du menu → fermeture (comportement Cursor-like).
  await page.getByRole("heading", { name: /Mes contenus sauvegardés/i }).click();
  await expect(menu).toHaveCount(0);
});

test("Agent IA : menu Publier + ⋯ sous une réponse (conversation mockée), avec Joindre des images", async ({ page }) => {
  // Conversation + réponse mockées : la barre d'actions se rend sans aucune
  // génération réelle (lecture seule).
  await page.route("**/chat/conversations", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([{ id: "e2e-conv", title: "Test ALE-188", created_at: "2026-07-01T10:00:00Z", updated_at: "2026-07-01T10:00:00Z" }]),
    })
  );
  await page.route("**/chat/conversations/e2e-conv/messages", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ messages: [
        { id: "m1", role: "user", content: "Écris un post de test." },
        { id: "m2", role: "assistant", content: "Voici un post de test ALE-188." },
      ] }),
    })
  );
  await gotoTab(page, "Agent IA");
  // Au montage, seule la liste est chargée : on ouvre la conversation mockée.
  await page.getByText("Test ALE-188").click();
  await expect(page.getByText("Voici un post de test ALE-188.")).toBeVisible();
  await checkActionsBar(page, { expectDelete: false });

  // Le menu « ⋯ » de l'Agent IA porte : Sauvegarder, Joindre des images, Image IA.
  const bar = page.locator(".post-actions-bar").first();
  await bar.getByRole("button", { name: "Plus d'actions" }).click();
  const menu = page.locator(".action-menu");
  await expect(menu.getByRole("menuitem", { name: /Sauvegarder/ })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: /Joindre des images/ })).toBeVisible();

  // Upload réel d'un PNG 1×1 : la miniature apparaît, « Retirer » la supprime.
  const onePxPng = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
    "base64"
  );
  await menu.locator('input[type="file"]').setInputFiles({ name: "test-ale-188.png", mimeType: "image/png", buffer: onePxPng });
  await expect(page.getByText(/1 image jointe au post LinkedIn/)).toBeVisible();
  await page.getByRole("button", { name: /Retirer/ }).click();
  await expect(page.getByText(/image jointe au post LinkedIn/)).toHaveCount(0);
});

test("Agent IA : édition manuelle du post proposé (éditeur inline, version modifiée affichée)", async ({ page }) => {
  await page.route("**/chat/conversations", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([{ id: "e2e-conv-edit", title: "Test édition", created_at: "2026-07-01T10:00:00Z", updated_at: "2026-07-01T10:00:00Z" }]),
    })
  );
  await page.route("**/chat/conversations/e2e-conv-edit/messages", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ messages: [
        { id: "m1", role: "user", content: "Écris un post de test." },
        { id: "m2", role: "assistant", content: "Texte proposé par l'agent." },
      ] }),
    })
  );
  await gotoTab(page, "Agent IA");
  await page.getByText("Test édition").click();
  await expect(page.getByText("Texte proposé par l'agent.")).toBeVisible();

  // « Modifier le post » dans le menu « ⋯ » → éditeur inline pré-rempli.
  const bar = page.locator(".post-actions-bar").first();
  await bar.getByRole("button", { name: "Plus d'actions" }).click();
  await page.locator(".action-menu").getByRole("menuitem", { name: /Modifier le post/ }).click();
  const editor = page.locator("textarea.variant-text");
  await expect(editor).toBeVisible();
  await expect(editor).toHaveValue("Texte proposé par l'agent.");

  // Enregistrer une retouche → panneau « Version modifiée » affiché, bulle intacte.
  await editor.fill("Texte retouché à la main.");
  await page.getByRole("button", { name: /Enregistrer/ }).click();
  await expect(page.getByText(/Version modifiée/)).toBeVisible();
  await expect(page.getByText("Texte retouché à la main.")).toBeVisible();
  await expect(page.getByText("Texte proposé par l'agent.")).toBeVisible();

  // Revenir au texte d'origine → le panneau disparaît.
  await bar.getByRole("button", { name: "Plus d'actions" }).click();
  await page.locator(".action-menu").getByRole("menuitem", { name: /Modifier le post/ }).click();
  await page.getByRole("button", { name: /Revenir au texte d'origine/ }).click();
  await expect(page.getByText(/Version modifiée/)).toHaveCount(0);
});

test("Contenu › Mes contenus : Image IA propose une image de référence depuis la banque de templates (ALE-221, tout mocké)", async ({ page }) => {
  await page.route("**/me/generated-posts", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify([
          { id: "e2e-ale-221", post: "Post de test ALE-221", topic: "Sujet test", created_at: "2026-07-08T10:00:00Z", media_items: [] },
        ]),
      });
    }
    return route.fallback();
  });
  // Rattachement de l'image (ALE-261) : persistée via PUT sur le post sauvegardé.
  await page.route("**/me/generated-posts/e2e-ale-221", (route) => {
    if (route.request().method() === "PUT") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ id: "e2e-ale-221", media_items: [{ url: "https://example.com/generated.png" }] }),
      });
    }
    return route.fallback();
  });
  await page.route("**/me/post-templates", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "tpl-e2e-1",
            structure_label: "Accroche choc + 3 bullets",
            structure_text: "1. Accroche\n2. Bullet\n3. Bullet\n4. CTA",
            image_url: "https://example.com/tpl.png",
          },
        ]),
      });
    }
    return route.fallback();
  });
  await page.route("**/generate-image/prompt", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ prompt: "Un prompt de test." }) })
  );
  // ALE-261 : la génération d'image passe désormais par une file d'attente
  // (job créé puis polled) — on mocke un job déjà `done` pour ne pas avoir à
  // simuler le polling dans ce test lecture seule.
  const onePxPng =
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
  let capturedBody: { reference_template_id?: string; target_key?: string } | null = null;
  await page.route("**/generate-image/jobs", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
    }
    if (route.request().method() === "POST") {
      capturedBody = route.request().postDataJSON();
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          id: "job-e2e-1",
          status: "done",
          target_key: capturedBody?.target_key,
          result: { image_data: onePxPng, prompt_used: "Un prompt de test.", credits: 95 },
          error: null,
        }),
      });
    }
    return route.fallback();
  });

  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Ma bibliothèque");
  const bar = page.locator(".post-actions-bar").first();
  await bar.getByRole("button", { name: "Plus d'actions" }).click();
  await page.locator(".action-menu").getByRole("menuitem", { name: /Générer une image IA/ }).click();

  // La vignette du template apparaît et se sélectionne. ALE-282 : la sélection doit
  // être explicite (état pressé + bandeau qui nomme la référence retenue).
  const thumbnail = page.getByRole("button", { name: "Accroche choc + 3 bullets" });
  await expect(thumbnail).toBeVisible();
  await expect(thumbnail).toHaveAttribute("aria-pressed", "false");
  await thumbnail.click();
  await expect(thumbnail).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText(/Inspiration : « Accroche choc \+ 3 bullets »/)).toBeVisible();

  await page.getByRole("button", { name: /Générer l'image/ }).click();
  await expect(page.getByText(/Image jointe au post/)).toBeVisible();
  expect(capturedBody?.reference_template_id).toBe("tpl-e2e-1");
  expect(capturedBody?.target_key).toBe("saved:e2e-ale-221");
});

// ALE-286 : l'onglet « Idée du jour » a disparu de la vue agence (il ne subsiste
// que dans la vue client) — le test qui couvrait la barre d'actions sur le post
// du jour est remplacé par celui de la file du Générateur, qui la porte désormais.

test("Contenu › Générateur : une ligne terminée se déplie et porte la barre d'actions (ALE-286, jobs mockés)", async ({ page }) => {
  // Le compte de test n'a pas forcément de post en file et on ne peut pas en
  // générer (lecture seule : ce serait un appel LLM payant) : on mocke la file.
  await page.route("**/generate/jobs", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "job-e2e-286",
            status: "done",
            topic: "Pourquoi les PME ratent leur premier projet IA",
            editorial_role: "story",
            web_search: false,
            count: 1,
            template_id: "tpl-e2e-286",
            result: {
              variants: [
                {
                  id: "post-e2e-286",
                  editorial_role: "story",
                  hook_type: "story",
                  strategy: "Raconter un échec client pour crédibiliser le cadrage.",
                  predicted_lift: "Connexion émotionnelle",
                  post: "Post de test ALE-286.",
                },
              ],
            },
            error: null,
            created_at: "2026-07-13T10:00:00Z",
            updated_at: "2026-07-13T10:02:00Z",
          },
        ]),
      });
    }
    return route.fallback();
  });
  await page.route("**/me/post-templates", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify([
          { id: "tpl-e2e-286", structure_label: "Story en 4 temps", structure_text: "Situation\nTension\nBascule\nLeçon" },
        ]),
      });
    }
    return route.fallback();
  });

  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Générateur de posts");

  // Une ligne = un post : sujet, rôle éditorial et structure utilisée, repliés.
  const line = page.locator(".post-queue-line").first();
  await expect(line).toBeVisible();
  await expect(line).toContainText("Pourquoi les PME ratent leur premier projet IA");
  await expect(line).toContainText("Story");
  await expect(line).toContainText("Story en 4 temps");
  await expect(page.locator(".post-actions-bar")).toHaveCount(0);

  // Clic → la ligne se déplie sur le post éditable et la barre d'actions complète.
  await line.click();
  await expect(line).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator("textarea.variant-text")).toHaveValue("Post de test ALE-286.");
  await checkActionsBar(page, { expectDelete: false });

  // Re-clic → repliée.
  await line.click();
  await expect(line).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(".post-actions-bar")).toHaveCount(0);
});
