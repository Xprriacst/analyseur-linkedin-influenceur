import { test, expect, Page } from "@playwright/test";
import { gotoTab } from "./helpers";

// 0065 — Avatar IA (HeyGen) : « Générer avec mon avatar IA » sur le pack Reel.
//
// Backend entièrement mocké (un rendu réel coûte ~2-3 $ chez HeyGen). Ce que ce
// spec verrouille, ce sont les deux pannes silencieuses possibles du câblage :
// (1) le SCRIPT (hook + script, tels qu'édités) et la CLÉ DE LIGNE doivent
//     partir au serveur — un script perdu en route lancerait un rendu vide ou
//     hors sujet, facturé quand même ;
// (2) la vidéo terminée doit REVENIR sur la bonne ligne et pré-remplir le bloc
//     de publication — sinon elle existe en base mais le client ne la voit
//     jamais et relance le rendu pour rien (le bug historique des images).

const REEL_JOB = {
  id: "job-ig-1",
  status: "done",
  platform: "instagram",
  topic: "6 outils IA testés sur 100",
  created_at: "2026-08-12T08:10:30Z",
  result: {
    variants: [
      {
        id: "gp-ig-1",
        platform: "instagram",
        post: "100 outils testés depuis janvier. 6 ont survécu.",
        reel_details: {
          hook: "J'ai testé 100 outils IA depuis le début de l'année.",
          script: "1. CE QU'ON DIT : le constat.\n2. CE QU'ON MONTRE : l'écran.",
          hashtags: ["#outilsia"],
        },
      },
    ],
  },
};

const HOSTED_VIDEO_URL = "https://media.zernio.com/avatar-reel-test.mp4";

async function mockCommon(page: Page) {
  await page.route("**/me/features", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ features: ["instagram"] }) })
  );
  await page.route("**/generate/jobs", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ contentType: "application/json", body: JSON.stringify([REEL_JOB]) })
      : route.fallback()
  );
  await page.route("**/me/instagram/status", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ connected: true, account_name: "clareo" }) })
  );
}

/** Instagram › Contenu, puis dépliage de la ligne du pack (cf. ig-reel-pack.spec). */
async function openPack(page: Page) {
  await page.goto("/");
  await page.locator(".nav-item", { hasText: "Instagram" }).first().click();
  await page.locator(".nav-item-sub", { hasText: "Contenu" }).last().click();
  await expect(page.getByRole("heading", { name: /Mes reels/ })).toBeVisible();
  await page.locator(".post-queue-line").first().click();
}

test("le script part au serveur et la vidéo revient pré-remplir la publication", async ({ page }) => {
  await mockCommon(page);

  // File de jobs vidéo cohérente : le POST capture le body et pousse un job
  // `queued` ; le polling suivant le voit `done` avec l'URL RE-HÉBERGÉE (jamais
  // l'URL HeyGen pré-signée — c'est le contrat du backend).
  let videoBody: { script?: string; target_key?: string } | null = null;
  const queue: unknown[] = [];
  await page.route("**/me/avatar/videos", (route) => {
    if (route.request().method() === "POST") {
      videoBody = route.request().postDataJSON();
      const job = {
        id: "avj-1",
        status: "queued",
        script: videoBody?.script || "",
        target_key: videoBody?.target_key || "",
        result: null,
        error: null,
      };
      queue.unshift(job);
      return route.fulfill({ contentType: "application/json", body: JSON.stringify(job) });
    }
    // GET : le job apparaît terminé dès le passage suivant du polling.
    const jobs = queue.map((j: any) => ({
      ...j,
      status: "done",
      result: { video_url: HOSTED_VIDEO_URL, duration: 41.5, credits: 900 },
    }));
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ jobs }) });
  });

  await openPack(page);
  await page.getByRole("button", { name: "Générer avec mon avatar IA" }).click();

  // (1) Le POST porte le hook PUIS le script (ce que l'avatar dira), et une clé
  // de ligne `reel:` — les perdre serait invisible à l'écran.
  await expect.poll(() => videoBody).not.toBeNull();
  expect(videoBody!.script).toContain("J'ai testé 100 outils IA");
  expect(videoBody!.script).toContain("CE QU'ON MONTRE");
  expect(videoBody!.target_key).toMatch(/^reel:/);

  // (2) La vidéo revient sur la ligne (polling à 8 s) et pré-remplit le bloc de
  // publication avec l'URL pérenne.
  await expect(page.locator(`video[src="${HOSTED_VIDEO_URL}"]`)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Vidéo avatar IA")).toBeVisible();
  // Le bouton de publication existant est utilisable tel quel avec cette vidéo.
  await expect(page.getByRole("button", { name: /Publier sur/ })).toBeEnabled();
});

test("Mon profil › Connexions : « Mon avatar IA » — le consentement verrouille l'upload", async ({ page }) => {
  await mockCommon(page);
  await page.route("**/me/avatar/status", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ available: true, avatar: null, voice: null }),
    })
  );

  await page.goto("/");
  await gotoTab(page, "Mon profil");
  await page.locator(".tab", { hasText: "Connexions" }).click();

  const row = page.locator("section.card", { hasText: "Mon avatar IA" });
  await expect(row).toBeVisible();
  await expect(row.getByText("À créer")).toBeVisible();

  await row.getByText("Mon avatar IA").click();
  // Sans la case « c'est bien moi », le choix de photo reste verrouillé — c'est
  // le seul garde-fou de consentement du parcours (HeyGen n'en impose pas sur
  // un photo avatar), il ne doit pas pouvoir être sauté.
  const uploadLabel = row.locator("label.secondary-button", { hasText: "Choisir ma photo" });
  await expect(uploadLabel).toHaveAttribute("aria-disabled", "true");
  await row.getByRole("checkbox").check();
  await expect(uploadLabel).toHaveAttribute("aria-disabled", "false");
});

test("compte sans le flag : rien de l'avatar IA ne s'affiche", async ({ page }) => {
  // Même état serveur, seul le flag manque (patron du spec autopilote) : ni la
  // ligne de Connexions, ni l'entrée Instagram dégrisée côté sidebar.
  await page.route("**/me/features", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ features: [] }) })
  );
  await page.goto("/");
  await gotoTab(page, "Mon profil");
  await page.locator(".tab", { hasText: "Connexions" }).click();
  await expect(page.locator(".tab.active", { hasText: "Connexions" })).toBeVisible();
  await expect(page.getByText("Mon avatar IA")).toHaveCount(0);
});
