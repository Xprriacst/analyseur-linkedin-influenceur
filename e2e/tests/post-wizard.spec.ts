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

test("la file ne montre que les 3 derniers posts, « Tout voir » déplie le reste (ALE-287)", async ({ page }) => {
  const job = (i: number) => ({
    id: `job-${i}`,
    status: "done",
    topic: `Post numéro ${i}`,
    editorial_role: "story",
    web_search: false,
    count: 1,
    template_id: null,
    result: { variants: [{ id: `p-${i}`, editorial_role: "story", hook_type: "story", strategy: "", predicted_lift: "", post: `Texte ${i}` }] },
    error: null,
    created_at: "2026-07-13T10:00:00Z",
    updated_at: "2026-07-13T10:00:00Z",
  });
  await page.route("**/generate/jobs", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ contentType: "application/json", body: JSON.stringify([1, 2, 3, 4, 5].map(job)) })
      : route.fallback()
  );

  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Générateur de posts");

  // 5 posts en base, 3 affichés.
  await expect(page.locator(".post-queue-line")).toHaveCount(3);
  await expect(page.getByText("Post numéro 1")).toBeVisible();
  await expect(page.getByText("Post numéro 4")).toHaveCount(0);

  await page.getByRole("button", { name: /Tout voir \(5\)/ }).click();
  await expect(page.locator(".post-queue-line")).toHaveCount(5);
  await expect(page.getByText("Post numéro 5")).toBeVisible();

  // Un post déplié hors des 3 premiers ne doit PAS disparaître au « Réduire » —
  // sinon on referme sous les yeux du client le post qu'il est en train de lire.
  await page.locator(".post-queue-line").nth(4).click();
  await expect(page.locator("textarea.variant-text")).toHaveValue("Texte 5");
  // Nom exact : « Réduire » seul matcherait aussi « Réduire la sidebar ».
  await page.getByRole("button", { name: "Réduire", exact: true }).click();
  await expect(page.getByText("Post numéro 5")).toBeVisible();
  await expect(page.locator("textarea.variant-text")).toHaveValue("Texte 5");
});

test("le réservoir d'idées est sur la page, et chaque idée lance le parcours (ALE-287)", async ({ page }) => {
  await mockEmptyQueue(page);
  const seeds = [{ id: "s1", text: "Le cadrage avant l'outil", used_at: null, comment: null }];
  await page.route("**/me/idea-seeds", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({ contentType: "application/json", body: JSON.stringify(seeds) });
    }
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      const created = { id: "s2", text: body.text, used_at: null, comment: null };
      seeds.push(created);
      return route.fulfill({ contentType: "application/json", body: JSON.stringify(created) });
    }
    return route.fallback();
  });

  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Générateur de posts");

  // Le réservoir a retrouvé une page (il ne vivait plus que dans la pop-up).
  await expect(page.getByRole("heading", { name: /Mes idées de posts/i })).toBeVisible();
  await expect(page.getByText("Le cadrage avant l'outil")).toBeVisible();

  // Ajout d'une idée depuis la page.
  await page.getByLabel(/Une idée de post/i).fill("Ce que coûte un projet IA mal cadré");
  await page.getByRole("button", { name: /^Ajouter/ }).click();
  await expect(page.getByText("Ce que coûte un projet IA mal cadré")).toBeVisible();

  // « Générer » sur une idée ouvre le parcours, déjà pré-rempli. Le bouton est
  // cherché DANS le réservoir : le gros bouton de la page ne doit pas répondre ici.
  await page.locator(".daily-reservoir").getByRole("button", { name: /^Générer$/ }).first().click();
  const modal = page.getByRole("dialog", { name: /Générer un post/i });
  await expect(modal.getByLabel(/De quoi veux-tu parler/i)).toHaveValue("Le cadrage avant l'outil");
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

test("« Fermer » laisse le post en ligne dans la file, cliquable pour reprendre", async ({ page }) => {
  await mockEmptyQueue(page);
  await page.route("**/me/idea-seeds", (route) =>
    route.request().method() === "GET" ? route.fulfill({ contentType: "application/json", body: "[]" }) : route.fallback()
  );
  await page.route("**/generate/editorial-role", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ editorial_role: "methodologie", reason: "Une méthode sera plus utile.", roles: [] }),
    })
  );
  await page.route("**/generate/structures", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        structures: [
          { id: "tpl-b", label: "Méthode en 5 étapes", structure_text: "1\n2\n3", post_text: null },
          { id: "tpl-a", label: "Story en 4 temps", structure_text: "S\nT\nB", post_text: null },
        ],
        recommended_id: "tpl-b",
      }),
    })
  );

  await gotoTab(page, "Contenu");
  await gotoSubTab(page, "Générateur de posts");

  // On va jusqu'à la dernière étape, et on change la structure pré-cochée : c'est
  // ce choix-là qu'on doit retrouver au retour.
  await page.getByRole("button", { name: /Générer un post/i }).click();
  const modal = page.getByRole("dialog", { name: /Générer un post/i });
  await modal.getByRole("button", { name: /J'ai une idée/i }).click();
  await modal.getByLabel(/De quoi veux-tu parler/i).fill("Les 4 niveaux de maîtrise n8n");
  await modal.getByRole("button", { name: /Continuer/i }).click();
  await modal.getByRole("button", { name: /Continuer/i }).click();
  await expect(modal.getByRole("heading", { name: /Sur quelle structure/i })).toBeVisible();
  await modal.getByRole("button", { name: /Story en 4 temps/ }).click();

  // Fermer ne doit RIEN jeter : le parcours coûte des crédits (les idées) et de
  // l'attente (reco d'angle, structures). Avant, tout repartait de zéro.
  await modal.getByRole("button", { name: /^Fermer$/ }).click();
  await expect(modal).toHaveCount(0);

  // Le post inachevé a SA ligne dans la file, qui dit où on en est.
  const draftLine = page.locator(".post-queue-line").first();
  await expect(draftLine).toContainText("Les 4 niveaux de maîtrise n8n");
  await expect(draftLine).toContainText("En cours");
  await expect(draftLine).toContainText("il reste à choisir la structure");

  // Un clic sur la ligne reprend le parcours EXACTEMENT où il en était — dont la
  // structure choisie, qui n'est ni la recommandée ni la première.
  await draftLine.click();
  const back = page.getByRole("dialog", { name: /Générer un post/i });
  await expect(back.getByRole("heading", { name: /Sur quelle structure/i })).toBeVisible();
  await expect(back.getByText(/Les 4 niveaux de maîtrise n8n/)).toBeVisible();
  await expect(back.getByRole("button", { name: /Story en 4 temps/ })).toHaveAttribute("aria-pressed", "true");
  await expect(back.getByRole("button", { name: /Méthode en 5 étapes/ })).toHaveAttribute("aria-pressed", "false");

  // Le gros bouton, lui, démarre bien un NOUVEAU post (il ne reprend pas celui-ci).
  await back.getByRole("button", { name: /^Fermer$/ }).click();
  await page.getByRole("button", { name: /Générer un post/i }).click();
  const fresh = page.getByRole("dialog", { name: /Générer un post/i });
  await expect(fresh.getByRole("heading", { name: /Par où on commence/i })).toBeVisible();
  await fresh.getByRole("button", { name: /^Fermer$/ }).click();
  // Ouvert puis refermé sans rien faire : pas de ligne fantôme. L'ancien parcours
  // est toujours là, lui.
  await expect(page.locator(".post-queue-line")).toHaveCount(1);

  // Et on peut jeter un parcours dont on ne veut plus.
  await page.locator(".post-queue-line").first().getByRole("button", { name: /Supprimer/i }).click();
  await expect(page.getByText(/Aucun post pour l'instant/i)).toBeVisible();
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
