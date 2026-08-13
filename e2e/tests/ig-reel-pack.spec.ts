import { test, expect, Page } from "@playwright/test";

// ALE-291 — « Mes reels » : le pack généré doit s'afficher, pas des champs vides.
//
// Le piège que ce spec verrouille : un pack Reel existe sous DEUX formes. Le
// modèle le produit À PLAT (hook/script/caption/hashtags), puis
// `db.save_generated_posts` le range dans la forme base — `post` porte la
// caption, le reste va dans `reel_details` — et c'est CETTE forme qui repart au
// front dans `result.variants`. Le front lisait la forme à plat : les quatre
// champs sortaient vides alors que le pack était complet en base, et la
// génération avait bien été facturée. Panne silencieuse, invisible côté serveur.
//
// Backend entièrement mocké : aucune génération, zéro crédit consommé.

const REEL_JOB_DB_SHAPE = {
  id: "job-ig-1",
  status: "done",
  platform: "instagram",
  topic: "6 outils IA testés sur 100",
  created_at: "2026-08-05T08:10:30Z",
  result: {
    variants: [
      {
        id: "gp-ig-1",
        platform: "instagram",
        // La caption vit dans `post`, PAS dans `caption`.
        post: "100 outils testés depuis janvier. 6 ont survécu.",
        reel_details: {
          hook: "J'ai testé 100 outils IA depuis le début de l'année.",
          // Le script ne porte QUE le texte dit ; ce qu'on montre vit à part.
          script: "94 ont fini à la poubelle.\nVoilà les 6 qui restent.",
          shots: ["Plan fixe, regard caméra.", "Texte incrusté : les 6 noms."],
          hashtags: ["#outilsia", "#automatisation"],
        },
      },
    ],
  },
};

async function mockIgQueue(page: Page, job: unknown) {
  await page.route("**/me/features", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ features: ["instagram"] }) })
  );
  await page.route("**/generate/jobs", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ contentType: "application/json", body: JSON.stringify([job]) })
      : route.fallback()
  );
}

/** Instagram › Contenu, puis on déplie la ligne du pack.
 *  `gotoTab` ne convient pas ici : depuis ALE-246 l'entête d'un réseau DÉPLIE
 *  (il ne navigue pas, donc il ne devient jamais `.active`) — ce sont les
 *  sous-onglets qui naviguent. Le « Contenu » d'Instagram est le dernier du DOM
 *  (celui de LinkedIn, ouvert par défaut, vient avant). */
async function openPack(page: Page) {
  await page.goto("/");
  await page.locator(".nav-item", { hasText: "Instagram" }).first().click();
  await page.locator(".nav-item-sub", { hasText: "Contenu" }).last().click();
  await expect(page.getByRole("heading", { name: /Mes reels/ })).toBeVisible();
  await page.locator(".post-queue-line").first().click();
}

test("le pack reel s'affiche depuis la forme base (post + reel_details)", async ({ page }) => {
  await mockIgQueue(page, REEL_JOB_DB_SHAPE);
  await openPack(page);

  // Les quatre champs sont remplis — c'est exactement ce qui manquait.
  await expect(page.getByLabel("Hook du reel")).toHaveValue(/testé 100 outils IA/);
  await expect(page.getByLabel("Script du reel")).toHaveValue(/94 ont fini à la poubelle/);
  await expect(page.getByLabel("Caption du reel")).toHaveValue(/100 outils testés depuis janvier/);
  await expect(page.getByLabel("Hashtags du reel")).toHaveValue("#outilsia #automatisation");

  // Le texte dit et le plan de tournage sont dans DEUX champs distincts : si le
  // tournage repassait dans le script, l'avatar IA le prononcerait à voix haute.
  await expect(page.getByLabel("Script du reel")).not.toHaveValue(/Plan fixe/);
  await expect(page.getByLabel("Plan de tournage du reel")).toHaveValue(
    "Plan fixe, regard caméra.\nTexte incrusté : les 6 noms.",
  );

  // Le titre de la ligne repliée porte le hook, pas le libellé de repli.
  await expect(page.locator(".post-queue-line").first()).not.toHaveText(/^Pack reel$/);
  await expect(page.locator(".error")).toHaveCount(0);
});

test("forme à plat (sauvegarde en échec) : le pack reste lisible", async ({ page }) => {
  // Si `save_generated_posts` échoue, les variants gardent la forme du modèle.
  // Le client a payé sa génération : elle doit rester exploitable.
  await mockIgQueue(page, {
    ...REEL_JOB_DB_SHAPE,
    result: {
      variants: [
        {
          id: "gp-ig-2",
          post: "",
          hook: "Hook resté à plat",
          script: "Script resté à plat",
          shots: ["Plan resté à plat"],
          caption: "Caption restée à plat",
          hashtags: ["#plat"],
        },
      ],
    },
  });
  await openPack(page);

  await expect(page.getByLabel("Hook du reel")).toHaveValue("Hook resté à plat");
  await expect(page.getByLabel("Script du reel")).toHaveValue("Script resté à plat");
  await expect(page.getByLabel("Plan de tournage du reel")).toHaveValue("Plan resté à plat");
  await expect(page.getByLabel("Caption du reel")).toHaveValue("Caption restée à plat");
  await expect(page.getByLabel("Hashtags du reel")).toHaveValue("#plat");
});
