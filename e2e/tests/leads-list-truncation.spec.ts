import { test, expect } from "@playwright/test";
import { gotoTab } from "./helpers";

// La liste Prospection est PLAFONNÉE côté serveur — et jusqu'au 2026-09-04 elle
// ne le disait pas. Sur un compte à 1 133 leads, elle affichait « 500 lead(s) …
// rien n'est masqué » : un mensonge par omission qui a fait conclure au client
// que des invitations déposées par son autopilote n'existaient pas (les leads
// concernés étaient hors fenêtre).
//
// Backend MOCKÉ, zéro coût. Ce spec verrouille la seule chose qu'un test
// fonctionnel ordinaire laisserait passer : que l'écran DISE quand il tronque.
// Une liste tronquée et une liste complète sont visuellement identiques.

function lead(i: number, score: number | null) {
  return {
    id: `lead-${i}`,
    profile_url: `https://www.linkedin.com/in/personne-${i}`,
    name: `Personne ${i}`,
    headline: "Freelance",
    score,
    signal_count: 1,
    status: "new",
    signals: [{ post_url: "import://abc123", author: "leads.csv" }],
  };
}

async function mockProspecting(page: import("@playwright/test").Page) {
  // La vue Pilote est le mode par défaut : sans ça, la sidebar n'a pas d'onglet
  // Prospection et le spec échoue sur la navigation, pas sur ce qu'il teste.
  await page.addInitScript(() => {
    localStorage.setItem("lkd_interface_mode", "expert");
  });
  await page.route("**/me/features", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ features: [] }) })
  );
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

test("une liste tronquée annonce le total réel, pas « rien n'est masqué »", async ({ page }) => {
  await mockProspecting(page);
  await page.route("**/me/leads", (route) =>
    route.fulfill({
      contentType: "application/json",
      // 3 leads rendus, 1 133 en base : exactement la situation de l'incident.
      body: JSON.stringify({ leads: [lead(1, 80), lead(2, 60), lead(3, 40)], total: 1133 }),
    })
  );

  await page.goto("/");
  await gotoTab(page, "Prospection");

  await expect(page.getByText(/3 lead\(s\) affichés sur/i)).toBeVisible();
  await expect(page.getByText(/1133/)).toBeVisible();
  // La phrase qui rendait la troncature invisible ne doit plus apparaître ici.
  await expect(page.getByText(/rien n'est masqué/i)).toHaveCount(0);
});

test("une liste complète ne parle pas de troncature", async ({ page }) => {
  await mockProspecting(page);
  await page.route("**/me/leads", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ leads: [lead(1, 80), lead(2, 60)], total: 2 }),
    })
  );

  await page.goto("/");
  await gotoTab(page, "Prospection");

  await expect(page.getByText(/2 lead\(s\) ·/i)).toBeVisible();
  await expect(page.getByText(/affichés sur/i)).toHaveCount(0);
});

test("un serveur qui n'envoie pas de total ne fait pas croire à une troncature", async ({ page }) => {
  // Rétro-compatibilité : le champ `total` est nouveau. Un backend plus ancien
  // (ou un compteur en échec, qui est fail-safe) ne doit pas produire un
  // avertissement de troncature qui serait faux.
  await mockProspecting(page);
  await page.route("**/me/leads", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ leads: [lead(1, 80)] }),
    })
  );

  await page.goto("/");
  await gotoTab(page, "Prospection");

  await expect(page.getByText(/1 lead\(s\) ·/i)).toBeVisible();
  await expect(page.getByText(/affichés sur/i)).toHaveCount(0);
});
