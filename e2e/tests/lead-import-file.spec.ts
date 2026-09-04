import { test, expect } from "@playwright/test";
import { gotoTab } from "./helpers";

// Import d'un fichier de leads Excel/CSV comme source de prospection (migration 0070).
//
// Backend entièrement MOCKÉ : ce spec ne parse rien côté serveur et ne coûte
// rien. Il verrouille les pannes de cet écran qui seraient silencieuses :
//
//  1. le FICHIER doit réellement partir au serveur (multipart). Un formulaire
//     qui poste sans le fichier donnerait un 422 systématique — ou pire, un
//     import vide « réussi » ;
//  2. à la fin du job, la liste de leads doit être RECHARGÉE (sinon les leads
//     sont en base mais l'écran reste vide, le client ré-importe pour rien) ;
//  3. les lignes ignorées doivent être RESTITUÉES au client — les taire ferait
//     passer un fichier à moitié lu pour un import complet ;
//  4. AUCUN compte LinkedIn connecté n'est requis (rien ne passe par Unipile),
//     contrairement à l'import de recherche voisin.

const CSV_CONTENT =
  "Nom;Poste;URL LinkedIn\n" +
  "Camille Roy;CMO;https://www.linkedin.com/in/camille-roy\n" +
  "Sans URL;CEO;\n";

const LEAD = {
  id: "lead-1",
  profile_url: "https://www.linkedin.com/in/camille-roy",
  name: "Camille Roy",
  headline: "CMO",
  signal_count: 1,
  status: "new",
  // Un lead importé d'un fichier n'a PAS commenté : le libellé « a commenté »
  // serait un mensonge d'affichage. La clé synthétique `import://…` porte la
  // nature de la source ; `author` porte le nom du fichier.
  signals: [{ post_url: "import://abc123", author: "leads.csv" }],
};

async function mockProspecting(page: import("@playwright/test").Page) {
  await page.route("**/me/features", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ features: [] }) })
  );
  // Compte LinkedIn NON connecté : l'import de fichier doit marcher quand même.
  await page.route("**/me/linkedin/outreach/status", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ configured: true, connected: false }),
    })
  );
  await page.route("**/me/lead-targeting", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ targeting: {} }) })
  );
}

test.beforeEach(async ({ page }) => {
  // La vue Pilote est le mode par défaut depuis le 03/09 : sans ce garde, le spec
  // atterrit sur un shell qui n'a pas d'onglet Prospection et échoue sur la
  // navigation, pas sur ce qu'il teste.
  await page.addInitScript(() => {
    localStorage.setItem("lkd_interface_mode", "expert");
  });
  await page.goto("/");
});

test("le fichier part au serveur, les lignes ignorées sont restituées et la liste se recharge", async ({ page }) => {
  await mockProspecting(page);

  // Liste vide AVANT l'import, peuplée après : preuve que l'écran se recharge
  // tout seul à la fin du job.
  let jobDone = false;
  await page.route("**/me/leads", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ leads: jobDone ? [LEAD] : [] }),
    })
  );

  let sentBody: string | null = null;
  await page.route("**/me/lead-imports", async (route) => {
    sentBody = route.request().postData();
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        source: { id: "src-1", post_url: "import://abc123", kind: "import" },
        job: { id: "job-1", source_id: "src-1", status: "queued", max_comments: 1, result: null, error: null },
        existing: false,
        profiles_count: 1,
        ignored_rows: 1,
      }),
    });
  });

  await page.route("**/me/lead-collection-jobs/job-1", async (route) => {
    jobDone = true;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "job-1",
        source_id: "src-1",
        status: "done",
        max_comments: 1,
        result: {
          comments_count: 1,
          leads: { inserted: 1, updated: 0 },
          ignored_rows: 1,
          total_rows: 2,
          credits: null,
        },
        error: null,
      }),
    });
  });

  await gotoTab(page, "Prospection");
  await page.getByRole("button", { name: /Importer un fichier de leads/i }).click();

  await page.getByLabel(/Fichier de leads/i).setInputFiles({
    name: "leads.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(CSV_CONTENT, "utf-8"),
  });
  await page.getByRole("button", { name: /Importer le fichier/i }).click();

  // 1. Le fichier est réellement parti : le corps multipart porte son nom ET
  //    son contenu (une URL du CSV). Sans ça, le serveur n'a rien à parser.
  await expect.poll(() => sentBody).not.toBeNull();
  expect(sentBody).toContain("leads.csv");
  expect(sentBody).toContain("linkedin.com/in/camille-roy");

  // 2+3. Fin du job : compte-rendu AVEC les lignes ignorées, et la liste se
  //      remplit sans action du client.
  await expect(page.getByText(/1 profil importé, dont 1 nouveau lead/i)).toBeVisible({ timeout: 15000 });
  await expect(page.getByText(/1 ligne ignorée/i)).toBeVisible();
  await expect(page.getByText("Camille Roy")).toBeVisible();
  const row = page.getByRole("button", { name: /Camille Roy/ });
  await expect(row).toContainText("importé depuis ton fichier");
  await expect(row).not.toContainText("a commenté");
  await expect(row).not.toContainText("trouvé dans ta recherche");
});

test("un fichier sans URL de profil affiche le 422 du serveur, jamais un succès vide", async ({ page }) => {
  await mockProspecting(page);
  await page.route("**/me/leads", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ leads: [] }) })
  );
  const detail =
    "Aucune URL de profil LinkedIn (linkedin.com/in/…) trouvée dans le fichier. " +
    "Ajoute une colonne avec le lien du profil de chaque prospect, puis réessaie.";
  await page.route("**/me/lead-imports", (route) =>
    route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail }) })
  );

  await gotoTab(page, "Prospection");
  await page.getByRole("button", { name: /Importer un fichier de leads/i }).click();
  await page.getByLabel(/Fichier de leads/i).setInputFiles({
    name: "emails.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("name,email\nAda,ada@example.com\n", "utf-8"),
  });
  await page.getByRole("button", { name: /Importer le fichier/i }).click();

  await expect(page.getByText(/Aucune URL de profil LinkedIn/i)).toBeVisible();
});
