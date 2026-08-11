import { test, expect, type Page } from "@playwright/test";

/**
 * Tunnel fondateurs SaaS (/founders, parcours anonyme) :
 * lien du SaaS → audit léger → questions SaaS → gains en ARR → simulation → essai.
 *
 * Backend entièrement mocké (zéro coût Apify/Claude/Stripe). Ce spec verrouille les
 * trois écarts qui feraient de ce tunnel une copie ratée de /start, tous invisibles
 * à l'œil nu sur une capture d'écran :
 *
 * 1. La projection doit être demandée avec `audience: "saas"`. Sans ça, l'écran
 *    afficherait la grille prestation (« panier moyen ») à un fondateur qui
 *    raisonne en ACV — des montants d'apparence normale, calculés sur la mauvaise
 *    hypothèse.
 * 2. Le tunnel doit se terminer sur l'ESSAI, jamais sur le Calendly de Tom ni sur
 *    le formulaire nom/e-mail/téléphone de /start : c'est toute la raison d'être
 *    de cette URI.
 * 3. Les questions doivent être celles de la variante SaaS. Des chips où le
 *    visiteur ne se reconnaît pas le poussent vers « Autre » et vident la
 *    qualification que ces écrans existent pour produire.
 * 4. L'entrée est le SITE du SaaS, donc aucun profil LinkedIn n'est lu : les
 *    écrans ne doivent JAMAIS afficher « aujourd'hui 0 » ni « 0 abonnés ». Le
 *    fondateur a un compte, on ne l'a simplement pas mesuré — annoncer zéro
 *    serait un chiffre faux sur son propre compte, en plein argumentaire.
 */

const PREVIEW = {
  handle: "",
  name: "Northstack",
  headline: "Analytics produit pour équipes SaaS B2B",
  avatar_url: "",
  // Entrée par le site : aucun scrape de profil, donc aucun compteur d'audience.
  posts_count: 0,
  followers: 0,
  connections: 0,
  niche: "Analytics produit pour équipes SaaS B2B",
  summary: "Premier paragraphe.\n\nDeuxième paragraphe.",
  hook: "Tu parles de ton produit, jamais du problème.",
  hashtags: ["#SaaS", "#ProductLed"],
  strengths: ["Ton direct", "Sujets concrets", "Bonne régularité"],
  improvements: ["Headline floue", "Pas de CTA", "Peu de preuves chiffrées"],
};

const range = (low: number, high: number) => ({ low, high });

function saasBand(key: string, label: string, revenue: [number, number]) {
  return {
    key,
    label,
    deal_value: 3600,
    projection: {
      followers_now: 0,
      followers_after: range(120, 450),
      followers_gain: range(120, 450),
      relations_per_month: range(40, 110),
      conversations_per_month: range(5, 20),
      clients_per_month: range(1, 4),
      revenue_per_month: range(revenue[0], revenue[1]),
    },
    assumptions: [
      "Montants exprimés en ARR signé (valeur annuelle des contrats fermés dans le mois).",
      `Panier moyen retenu : ${label}.`,
    ],
  };
}

async function mockBackend(page: Page) {
  await page.route("**/onboarding/draft", (route) =>
    route.fulfill({
      json: {
        profile: { display_name: "Léa Fondatrice", core_offer: "Un SaaS vendu en démo" },
        preview: PREVIEW,
        sources: { description: false, linkedin_apify: true, website_summary: false },
      },
    }),
  );
  await page.route("**/billing/plan", (route) =>
    route.fulfill({
      json: {
        enabled: true,
        trial_days: 7,
        plan: { credits: 1000, amount: 49, currency: "eur", interval: "month" },
      },
    }),
  );
}

/** Va de la landing jusqu'à la simulation, en exposant le corps reçu par la projection. */
async function reachSimulation(page: Page): Promise<{ projectionBody: () => any }> {
  let projectionBody: any = null;
  await page.route("**/onboarding/projection", (route) => {
    projectionBody = route.request().postDataJSON();
    return route.fulfill({
      json: {
        default_band: "smb",
        deal_label: "Ton ACV moyen (ce que rapporte un client sur 12 mois)",
        revenue_label: "Nouvel ARR signé par mois",
        bands: [
          saasBand("self_serve", "Moins de 1 200 € / an", [700, 2800]),
          saasBand("smb", "1 200 à 6 000 € / an", [3600, 14400]),
          saasBand("midmarket", "6 000 à 25 000 € / an", [15000, 60000]),
        ],
      },
    });
  });

  await page.goto("/founders");
  // Premier écran : le lien du SaaS, pas le profil LinkedIn.
  await page.getByPlaceholder("https://ton-saas.com").fill("https://northstack.io");
  await page.getByRole("button", { name: "Analyser" }).click();

  // Audit léger (écran 1) puis son détail (écran 2).
  await page.getByRole("button", { name: "Voir mon potentiel" }).click();
  await page.getByRole("button", { name: "Continuer", exact: true }).click();

  // (3) Questions de la variante SaaS : l'ICP, pas « À qui tu t'adresses ? ».
  await expect(page.getByText("Ton ICP — à qui tu vends ?")).toBeVisible();
  await page.getByRole("button", { name: "Une cible précise" }).click();
  await expect(page.getByRole("button", { name: "Fondateurs & CEO de SaaS" })).toBeVisible();
  await page.getByRole("button", { name: "CTO & équipes tech" }).click();
  await page.getByRole("button", { name: "Continuer", exact: true }).click();

  await expect(page.getByText("Ta catégorie de produit")).toBeVisible();
  await page.getByRole("button", { name: "DevTools & infra" }).click();
  await page.getByRole("button", { name: /Voir ce que je peux gagner/ }).click();

  // Les montants sont annoncés pour ce qu'ils sont : de l'ARR signé.
  await expect(page.getByText("Nouvel ARR signé par mois")).toBeVisible();
  await expect(page.locator(".onb-gain-money")).toContainText("3 600");
  await page.getByRole("button", { name: "6 000 à 25 000 € / an" }).click();
  await expect(page.locator(".onb-gain-money")).toContainText("15 000");
  await page.locator(".onb-screen").getByRole("button", { name: "Continuer", exact: true }).click();

  // (4) Aucun compteur d'audience inventé, ni dans les gains ni dans la simulation.
  await expect(page.locator(".onb-sim-grid")).not.toContainText("0 abonnés");
  await expect(page.locator(".onb-screen")).not.toContainText("aujourd'hui 0");
  return { projectionBody: () => projectionBody };
}

test.describe("Tunnel fondateurs SaaS (anonyme)", () => {
  test("projection en grille SaaS, sortie sur l'essai gratuit et non sur le Calendly", async ({ page }) => {
    await mockBackend(page);
    const { projectionBody } = await reachSimulation(page);

    // (1) La grille demandée est bien celle des fondateurs. Sans scrape de profil,
    // les compteurs partent à 0 — c'est la projection qui applique ses planchers,
    // et c'est bien « audience: saas » qui décide de la grille ACV.
    expect(projectionBody()).toMatchObject({ audience: "saas" });

    // (2) Fin de tunnel : l'essai, avec sa durée annoncée par le serveur — et
    // AUCUN des deux artefacts du tunnel /start.
    const trialCta = page.getByRole("button", { name: /Démarrer mes 7 jours gratuits/ });
    await expect(trialCta).toBeVisible();
    await expect(page.getByRole("button", { name: /Recevoir mon audit complet gratuit/ })).toHaveCount(0);

    await trialCta.click();

    // Écran de compte : l'e-mail est capturé ici, pas dans un formulaire de lead.
    await expect(page.getByRole("heading", { name: "Crée ton compte fondateur" })).toBeVisible();
    await expect(page.getByPlaceholder("toi@ton-saas.com")).toBeVisible();
    // Le téléphone du tunnel audit ne doit jamais être demandé ici.
    await expect(page.getByPlaceholder("06 12 34 56 78")).toHaveCount(0);
    // Les réponses SaaS sont bien remontées jusqu'à cet écran.
    await expect(page.getByText(/ICP : .*CTO & équipes tech/)).toBeVisible();
  });

  test("les réponses survivent à un rechargement en cours d'inscription", async ({ page }) => {
    await mockBackend(page);
    await reachSimulation(page);
    await page.getByRole("button", { name: /Démarrer mes 7 jours gratuits/ }).click();
    await expect(page.getByRole("heading", { name: "Crée ton compte fondateur" })).toBeVisible();

    // Rechargement : sans la réserve de réponses, le fondateur repartirait de
    // l'analyse (donc d'un scrape payant) et perdrait sa qualification.
    await page.reload();
    await expect(page.getByRole("heading", { name: "Crée ton compte fondateur" })).toBeVisible();
    await expect(page.getByText(/ICP : .*CTO & équipes tech/)).toBeVisible();
  });

  test("projection injoignable : le tunnel mène quand même à l'essai", async ({ page }) => {
    await mockBackend(page);
    await page.route("**/onboarding/projection", (route) => route.fulfill({ status: 500, json: {} }));

    await page.goto("/founders");
    await page.getByPlaceholder("https://ton-saas.com").fill("https://northstack.io");
    await page.getByRole("button", { name: "Analyser" }).click();
    await page.getByRole("button", { name: "Voir mon potentiel" }).click();
    await page.getByRole("button", { name: "Continuer", exact: true }).click();
    await page.getByRole("button", { name: "Continuer", exact: true }).click();
    await page.getByRole("button", { name: /Voir ce que je peux gagner/ }).click();

    // Un écran de mise en scène en panne ne doit pas coûter le prospect : on
    // atterrit sur la création de compte, pas sur un écran vide ni sur /start.
    await expect(page.getByRole("heading", { name: "Crée ton compte fondateur" })).toBeVisible();
  });
});
