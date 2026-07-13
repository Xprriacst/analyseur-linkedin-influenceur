import { test, expect } from "@playwright/test";
import { gotoTab, gotoSubTab } from "./helpers";

// ALE-286 : parcours guidé de génération. Point de départ → idée → profil
// éditorial (recommandé par l'IA) → structure choisie parmi 3 → UN post.
//
// Les appels PAYANTS sont mockés (/ideas = 3 crédits, /generate/jobs = 5) : ce
// spec vérifie le CÂBLAGE — que le parcours converge, que la reco de l'IA est
// pré-cochée à chaque choix, et surtout que l'idée, l'angle et LA STRUCTURE
// retenue partent bien tous les trois au serveur. Une régression qui perdrait la
// structure en route (c'est déjà arrivé : ALE-216) ne se verrait pas autrement —
// le post serait généré, simplement sans la forme demandée.

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

test("le parcours mène de l'idée à UN post en file, sur la structure choisie", async ({ page }) => {
  await page.route("**/me/post-templates", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({
          contentType: "application/json",
          body: JSON.stringify([
            { id: "tpl-a", structure_label: "Story en 4 temps", structure_text: "S\nT\nB\nL" },
            { id: "tpl-b", structure_label: "Méthode en 5 étapes", structure_text: "1\n2\n3\n4\n5" },
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
  await page.route("**/generate/structures", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        structures: [
          { id: "tpl-b", label: "Méthode en 5 étapes", structure_text: "1\n2\n3\n4\n5", post_text: null },
          { id: "tpl-a", label: "Story en 4 temps", structure_text: "S\nT\nB\nL", post_text: null },
          { id: "tpl-c", label: "Contre-pied argumenté", structure_text: "Thèse\nAntithèse", post_text: null },
        ],
        recommended_id: "tpl-b",
      }),
    })
  );

  // File d'attente cohérente : le job créé par le POST doit être RENDU par le GET
  // suivant. Sans ça, le polling de la file écraserait la ligne qu'on vient
  // d'ajouter et le test deviendrait une course.
  let jobBody: { topic?: string; editorial_role?: string; template_id?: string; count?: number } | null = null;
  const queue: unknown[] = [];
  await page.route("**/generate/jobs", (route) => {
    if (route.request().method() === "POST") {
      jobBody = route.request().postDataJSON();
      const job = {
        id: "job-a",
        status: "queued",
        topic: jobBody?.topic ?? "",
        editorial_role: jobBody?.editorial_role ?? "",
        web_search: false,
        count: 1,
        template_id: jobBody?.template_id ?? null,
        result: null,
        error: null,
        created_at: "2026-07-13T10:00:00Z",
        updated_at: "2026-07-13T10:00:00Z",
      };
      queue.unshift(job);
      return route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...job, credits: 95 }) });
    }
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(queue) });
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
  await expect(modal.getByRole("button", { name: /Méthodologie/ })).toHaveAttribute("aria-pressed", "true");
  await expect(modal.getByText(/Recommandé.*plus utile qu'un constat/i)).toBeVisible();
  await expect(modal.getByRole("button", { name: /^Story/ })).toHaveAttribute("aria-pressed", "false");
  await modal.getByRole("button", { name: /Continuer/i }).click();

  // 3. Structure : 3 propositions, la plus adaptée pré-cochée + une échappatoire
  //    « structure libre ». Le client change d'avis et prend la Story.
  await expect(modal.getByRole("heading", { name: /Sur quelle structure/i })).toBeVisible();
  await expect(modal.getByRole("button", { name: /Méthode en 5 étapes/ })).toHaveAttribute("aria-pressed", "true");
  await expect(modal.getByText(/La plus adaptée à ton idée/i)).toBeVisible();
  await expect(modal.getByRole("button", { name: /Structure libre/ })).toBeVisible();
  await modal.getByRole("button", { name: /Story en 4 temps/ }).click();
  await expect(modal.getByRole("button", { name: /Story en 4 temps/ })).toHaveAttribute("aria-pressed", "true");
  await expect(modal.getByRole("button", { name: /Méthode en 5 étapes/ })).toHaveAttribute("aria-pressed", "false");

  // 4. Un seul post part, sur la structure retenue.
  await modal.getByRole("button", { name: /Générer le post/i }).click();
  await expect(modal).toHaveCount(0);

  const lines = page.locator(".post-queue-line");
  await expect(lines).toHaveCount(1);
  await expect(lines.first()).toContainText("Story en 4 temps");
  await expect(page.getByText(/1 en cours/)).toBeVisible();

  // LA vérification : idée, angle ET structure arrivent bien au serveur. Perdre la
  // structure en route est un bug déjà vécu (ALE-216) et parfaitement silencieux.
  expect(jobBody?.topic).toBe("Pourquoi les PME ratent leur projet IA sur le cadrage");
  expect(jobBody?.editorial_role).toBe("methodologie");
  expect(jobBody?.template_id).toBe("tpl-a");
  expect(jobBody?.count).toBe(1);
});

test("bibliothèque vide : le parcours propose la structure libre et n'est pas bloqué", async ({ page }) => {
  await mockEmptyQueue(page);
  await page.route("**/me/idea-seeds", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ contentType: "application/json", body: "[]" })
      : route.fallback()
  );
  await page.route("**/generate/editorial-role", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ editorial_role: "story", reason: "C'est du vécu.", roles: [] }),
    })
  );
  // Compte neuf : aucune structure à proposer.
  await page.route("**/generate/structures", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ structures: [], recommended_id: null }) })
  );

  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Générateur de posts");
  await page.getByRole("button", { name: /Générer un post/i }).click();
  const modal = page.getByRole("dialog", { name: /Générer un post/i });
  await modal.getByRole("button", { name: /J'ai une idée/i }).click();
  await modal.getByLabel(/De quoi veux-tu parler/i).fill("Mon idée à moi");
  await modal.getByRole("button", { name: /Continuer/i }).click();
  await modal.getByRole("button", { name: /Continuer/i }).click();

  // Seule option, pré-cochée, et le bouton reste actif : on ne coince personne
  // sur une étape sans choix.
  await expect(modal.getByRole("heading", { name: /Sur quelle structure/i })).toBeVisible();
  await expect(modal.getByRole("button", { name: /Structure libre/ })).toHaveAttribute("aria-pressed", "true");
  await expect(modal.getByText(/Ta bibliothèque est vide/i)).toBeVisible();
  await expect(modal.getByRole("button", { name: /Générer le post/i })).toBeEnabled();
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
