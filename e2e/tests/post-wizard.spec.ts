import { test, expect } from "@playwright/test";
import { gotoTab, gotoSubTab } from "./helpers";

// ALE-286 : parcours guidé de génération. Point de départ → idée → profil
// éditorial (recommandé par l'IA) → 3 posts sur 3 structures différentes.
//
// Les appels PAYANTS sont mockés (/ideas = 3 crédits, /generate/wizard = 15) :
// ce spec vérifie le CÂBLAGE — que le parcours converge, que le rôle recommandé
// est bien pré-coché, et surtout que les 3 jobs rendus atterrissent en 3 LIGNES
// distinctes dans la file. C'est la promesse du parcours ; une régression qui
// n'en afficherait qu'une passerait autrement inaperçue.

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

/** File vide au départ : les lignes qu'on observera viennent bien du parcours. */
async function mockEmptyQueue(page: import("@playwright/test").Page) {
  await page.route("**/generate/jobs", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
    }
    return route.fallback();
  });
}

test("le parcours mène de l'idée aux 3 posts en file (3 lignes, 3 structures)", async ({ page }) => {
  await mockEmptyQueue(page);
  await page.route("**/me/post-templates", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({
          contentType: "application/json",
          body: JSON.stringify([
            { id: "tpl-a", structure_label: "Story en 4 temps", structure_text: "S\nT\nB\nL" },
            { id: "tpl-b", structure_label: "Méthode en 5 étapes", structure_text: "1\n2\n3\n4\n5" },
            { id: "tpl-c", structure_label: "Contre-pied argumenté", structure_text: "Thèse\nAntithèse" },
          ]),
        })
      : route.fallback()
  );
  await page.route("**/me/idea-seeds", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({
          contentType: "application/json",
          body: JSON.stringify([{ id: "seed-1", text: "Idée mise de côté la semaine dernière", used_at: null }]),
        })
      : route.fallback()
  );
  await page.route("**/generate/editorial-role", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        editorial_role: "methodologie",
        reason: "Ton idée décrit une erreur évitable : une méthode sera plus utile qu'un constat.",
        roles: [],
      }),
    })
  );

  let wizardBody: { idea?: string; editorial_role?: string } | null = null;
  await page.route("**/generate/wizard", (route) => {
    wizardBody = route.request().postDataJSON();
    const job = (id: string, templateId: string) => ({
      id,
      status: "queued",
      topic: wizardBody?.idea ?? "",
      editorial_role: wizardBody?.editorial_role ?? "",
      web_search: false,
      count: 1,
      template_id: templateId,
      result: null,
      error: null,
      created_at: "2026-07-13T10:00:00Z",
      updated_at: "2026-07-13T10:00:00Z",
    });
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        jobs: [job("job-a", "tpl-a"), job("job-b", "tpl-b"), job("job-c", "tpl-c")],
        credits: 85,
      }),
    });
  });

  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Générateur de posts");
  await expect(page.getByText(/Aucun post pour l'instant/i)).toBeVisible();

  // 1. Point de départ : « J'ai une idée ».
  await page.getByRole("button", { name: /Générer un post/i }).click();
  const modal = page.getByRole("dialog", { name: /Générer un post/i });
  await modal.getByRole("button", { name: /J'ai une idée/i }).click();

  // Le réservoir d'idées est bien là (il a suivi l'onglet « Idée du jour » supprimé) :
  // un clic recopie l'idée mise de côté dans le champ.
  await modal.getByRole("button", { name: /Idée mise de côté la semaine dernière/i }).click();
  await expect(modal.getByLabel(/De quoi veux-tu parler/i)).toHaveValue("Idée mise de côté la semaine dernière");

  await modal.getByLabel(/De quoi veux-tu parler/i).fill("Pourquoi les PME ratent leur projet IA sur le cadrage");
  await modal.getByRole("button", { name: /Continuer/i }).click();

  // 2. Profil éditorial : la reco de l'IA est PRÉ-COCHÉE et justifiée — le client
  //    garde la main (les 7 rôles restent proposés).
  await expect(modal.getByRole("heading", { name: /Quel angle pour ce post/i })).toBeVisible();
  const recommended = modal.getByRole("button", { name: /Méthodologie/ });
  await expect(recommended).toHaveAttribute("aria-pressed", "true");
  await expect(modal.getByText(/Recommandé.*plus utile qu'un constat/i)).toBeVisible();
  await expect(modal.getByRole("button", { name: /^Story/ })).toHaveAttribute("aria-pressed", "false");

  // 3. Lancement : 3 posts, 3 structures.
  await modal.getByRole("button", { name: /Générer 3 posts/i }).click();
  await expect(modal).toHaveCount(0);

  // LA vérification : 3 jobs rendus → 3 LIGNES distinctes en file, une par structure.
  const lines = page.locator(".post-queue-line");
  await expect(lines).toHaveCount(3);
  await expect(page.locator(".post-queue-row", { hasText: "Story en 4 temps" })).toHaveCount(1);
  await expect(page.locator(".post-queue-row", { hasText: "Méthode en 5 étapes" })).toHaveCount(1);
  await expect(page.locator(".post-queue-row", { hasText: "Contre-pied argumenté" })).toHaveCount(1);
  // Encore en vol : chaque ligne s'annonce en attente et propose de s'annuler.
  await expect(page.getByText(/3 en cours/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Annuler/i })).toHaveCount(3);

  // L'idée et le rôle retenus sont bien ceux partis au serveur.
  expect(wizardBody?.idea).toBe("Pourquoi les PME ratent leur projet IA sur le cadrage");
  expect(wizardBody?.editorial_role).toBe("methodologie");
});

test("« J'ai une inspiration » : le post lu devient l'angle proposé, ajustable", async ({ page }) => {
  await mockEmptyQueue(page);
  await page.route("**/generate/inspiration", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        text: "Trouver un bon freelance rapidement, c'est l'équation impossible…",
        author: "Josselin Martin",
        url: "https://www.linkedin.com/posts/exemple",
        image_url: null,
        angle: "Montrer comment un message ciblé débloque une opportunité en 48h",
      }),
    })
  );

  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Générateur de posts");
  await page.getByRole("button", { name: /Générer un post/i }).click();
  const modal = page.getByRole("dialog", { name: /Générer un post/i });
  await modal.getByRole("button", { name: /J'ai une inspiration/i }).click();

  await modal.getByLabel(/Lien du post LinkedIn/i).fill("https://www.linkedin.com/posts/exemple");
  await modal.getByRole("button", { name: /Lire le post/i }).click();

  // Le post lu est montré (avec son auteur) et l'angle qu'on en tire est
  // pré-rempli — mais éditable : c'est une proposition, pas une décision.
  await expect(modal.getByText(/Post lu — Josselin Martin/i)).toBeVisible();
  await expect(modal.getByText(/l'équation impossible/i)).toBeVisible();
  const angle = modal.getByLabel(/L'angle qu'on en tire pour toi/i);
  await expect(angle).toHaveValue("Montrer comment un message ciblé débloque une opportunité en 48h");
  await angle.fill("Mon angle à moi");
  await expect(modal.getByRole("button", { name: /Continuer/i })).toBeEnabled();
});
