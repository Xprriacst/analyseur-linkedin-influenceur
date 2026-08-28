import { test, expect, Page } from "@playwright/test";

// Backlog Notion — « Ma bibliothèque Instagram au niveau LinkedIn », lot 1
// (import par lien + trames réutilisables à la génération de reels).
//
// Avant ce lot, Instagram › Contenu › Ma bibliothèque ne listait que les packs
// déjà générés et sauvegardés — aucun moyen d'y importer une référence externe
// ni de la réutiliser comme trame. Ce spec verrouille le câblage ajouté :
// - le formulaire d'ajout (lien ET texte collé) part bien au serveur avec
//   `platform: "instagram"`, jamais sur l'endpoint LinkedIn ;
// - une trame de bibliothèque (id préfixé `lib:`) est bien sélectionnable et
//   part au lancement d'un reel, exactement comme un id du catalogue statique
//   — perdre ce préfixe en route romprait silencieusement le lien entre la
//   trame choisie et celle utilisée pour la génération.
//
// Backend entièrement mocké : aucune génération, zéro crédit consommé.

async function withInstagramFeature(page: Page) {
  await page.route("**/me/features", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ features: ["instagram"] }) })
  );
}

/** Instagram › Contenu › Ma bibliothèque (mêmes pièges de navigation que
 *  ig-reel-pack.spec.ts : l'entête de réseau déplie, ce sont les sous-onglets
 *  qui naviguent, et LinkedIn est toujours avant Instagram dans le DOM). */
async function openInstagramLibrary(page: Page) {
  await page.goto("/");
  await page.locator(".nav-item", { hasText: "Instagram" }).first().click();
  await page.locator(".nav-item-sub", { hasText: "Contenu" }).last().click();
  await expect(page.getByRole("heading", { name: /Générateur de reels/ })).toBeVisible();
  await page.locator(".tab", { hasText: "Ma bibliothèque" }).last().click();
  await expect(page.getByRole("heading", { name: /Ajouter à ma bibliothèque/ })).toBeVisible();
}

test("ajouter un reel par lien part au serveur avec platform=instagram, jamais l'endpoint LinkedIn", async ({ page }) => {
  await withInstagramFeature(page);
  await page.route("**/me/generated-posts?platform=instagram", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify([]) })
  );

  let body: Record<string, unknown> | null = null;
  await page.route("**/me/post-templates?platform=instagram", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify([]) })
  );
  await page.route("**/me/post-templates", (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    body = route.request().postDataJSON();
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "tpl-ig-1",
        platform: "instagram",
        structure_label: "Hook question + démo",
        post_text: "Une caption Instagram importée automatiquement.",
      }),
    });
  });

  await openInstagramLibrary(page);
  await page.getByPlaceholder(/instagram\.com\/reel/).fill("https://www.instagram.com/reel/CxAbC123/");
  await page.getByRole("button", { name: /^Ajouter$/ }).click();

  await expect.poll(() => body).not.toBeNull();
  expect(body?.url).toBe("https://www.instagram.com/reel/CxAbC123/");
  expect(body?.platform).toBe("instagram");
  await expect(page.getByText("Hook question + démo")).toBeVisible();
});

test("texte collé (sans lien) part aussi avec platform=instagram", async ({ page }) => {
  await withInstagramFeature(page);
  await page.route("**/me/generated-posts?platform=instagram", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify([]) })
  );
  await page.route("**/me/post-templates?platform=instagram", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify([]) })
  );

  let body: Record<string, unknown> | null = null;
  await page.route("**/me/post-templates", (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    body = route.request().postDataJSON();
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ id: "tpl-ig-2", platform: "instagram", post_text: body?.text }),
    });
  });

  await openInstagramLibrary(page);
  await page.getByText(/Plus d'options — texte collé/).click();
  await page.getByPlaceholder(/colle la caption\/le script directement/i).fill(
    "Le script d'un reel qui a bien marché, collé directement."
  );
  await page.getByRole("button", { name: /^Ajouter$/ }).click();

  await expect.poll(() => body).not.toBeNull();
  expect(body?.url).toBeNull();
  expect(body?.text).toBe("Le script d'un reel qui a bien marché, collé directement.");
  expect(body?.platform).toBe("instagram");
});

test("une trame de la bibliothèque (id lib:) est sélectionnable et part telle quelle au lancement du reel", async ({ page }) => {
  await withInstagramFeature(page);
  await page.route("**/generate/jobs", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
    }
    return route.fallback();
  });
  await page.route("**/me/idea-seeds*", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ contentType: "application/json", body: JSON.stringify([]) })
      : route.fallback()
  );
  await page.route("**/generate/editorial-role", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ editorial_role: "story", reason: "Un reel qui raconte marche mieux ici.", roles: [] }),
    })
  );
  // Le backend mélange bibliothèque (id "lib:") et catalogue statique — ce spec
  // ne teste QUE le câblage front, le mélange lui-même est verrouillé côté
  // backend (tests/test_instagram_library.py::InstagramTramesEndpointTest).
  await page.route("**/generate/instagram/trames", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        trames: [
          { id: "lib:abc-123", label: "Ma trame perso", description: "Hook question, puis démonstration en 3 temps." },
          { id: "storytelling", label: "Storytelling", description: "Une anecdote, une leçon." },
        ],
      }),
    })
  );

  let jobBody: Record<string, unknown> | null = null;
  await page.route("**/generate/jobs", (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    jobBody = route.request().postDataJSON();
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "job-ig-1", status: "queued", platform: "instagram",
        topic: jobBody?.topic ?? "", ig_trame_id: jobBody?.ig_trame_id ?? null,
        result: null, error: null, created_at: "2026-08-28T10:00:00Z", updated_at: "2026-08-28T10:00:00Z",
        credits: 92,
      }),
    });
  });

  await page.goto("/");
  await page.locator(".nav-item", { hasText: "Instagram" }).first().click();
  await page.locator(".nav-item-sub", { hasText: "Contenu" }).last().click();
  await page.getByRole("button", { name: /Générer un reel/i }).click();
  const modal = page.getByRole("dialog", { name: /Générer un post/i });
  await modal.getByRole("button", { name: /J'ai une idée/i }).click();
  await modal.getByLabel(/De quoi veux-tu parler/i).fill("Le conseil que je donne le plus souvent à mes clients");
  await modal.getByRole("button", { name: /Continuer/i }).click();

  await expect(modal.getByRole("heading", { name: /Quel angle pour ce reel/i })).toBeVisible();
  await modal.getByRole("button", { name: /Continuer/i }).click();

  await expect(modal.getByRole("heading", { name: /Sur quelle trame/i })).toBeVisible();
  await modal.getByRole("button", { name: /Ma trame perso/ }).click();
  await expect(modal.getByRole("button", { name: /Ma trame perso/ })).toHaveAttribute("aria-pressed", "true");

  await modal.getByRole("button", { name: /Générer le reel/i }).click();
  await expect(modal).toHaveCount(0);

  // La vérification centrale : l'id "lib:" arrive intact au serveur — un
  // dépouillement du préfixe (ou un id de catalogue substitué) romprait le
  // lien avec la trame réellement choisie, sans qu'aucune erreur ne s'affiche.
  expect(jobBody?.ig_trame_id).toBe("lib:abc-123");
  expect(jobBody?.platform).toBe("instagram");
});
