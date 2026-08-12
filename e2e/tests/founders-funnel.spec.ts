import { test, expect, type Page } from "@playwright/test";

/**
 * Tunnel fondateurs SaaS (/founders, parcours anonyme) :
 * landing de vente → lien du SaaS → scan (avec stade + obstacles posés PENDANT
 * l'attente) → audit léger → questions SaaS → gains en ARR (avec courbe de
 * progression) → simulation → closing (miroir des obstacles, ROI, roadmap) → essai.
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
 * 5. Le closing rend au visiteur SES obstacles (effet miroir) et un ROI calculé
 *    sur l'ACV qu'il vient de choisir : si l'un des deux se perdait en route,
 *    l'écran redeviendrait un argumentaire générique — d'apparence normale.
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
  await page.route("**/onboarding/founders-lead", (route) => route.fulfill({ json: { ok: true } }));
}

/**
 * Passe la porte d'entrée de la landing (e-mail de rareté) et retourne le corps
 * réellement POSTé — si l'e-mail ne partait pas au serveur, la capture de leads
 * serait un champ décoratif : aucun visiteur perdu ne serait relançable.
 */
async function passGate(page: Page, email = "lea@northstack.io"): Promise<{ leadBody: () => any }> {
  let leadBody: any = null;
  await page.route("**/onboarding/founders-lead", (route) => {
    leadBody = route.request().postDataJSON();
    return route.fulfill({ json: { ok: true } });
  });
  await expect(page.getByText(/on vérifie qu'il reste une place/)).toBeVisible();
  await page.getByPlaceholder("toi@ton-saas.com").fill(email);
  await page.getByRole("button", { name: "Analyser mon SaaS" }).first().click();
  return { leadBody: () => leadBody };
}

/** Va de la landing jusqu'à la simulation, en exposant le corps reçu par la projection. */
async function reachSimulation(page: Page): Promise<{ projectionBody: () => any; leadBody: () => any }> {
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
  // Landing de vente d'abord : la promesse, puis la porte d'entrée e-mail
  // (rareté réelle : 20 comptes/mois) qui lance l'analyse.
  await expect(page.getByRole("heading", { name: /Le LinkedIn qui remplit ton pipeline/ })).toBeVisible();
  const { leadBody } = await passGate(page);

  // Premier écran du tunnel : le lien du SaaS, pas le profil LinkedIn.
  await page.getByPlaceholder("https://ton-saas.com").fill("https://northstack.io");
  await page.getByRole("button", { name: "Analyser" }).click();

  // Pendant le scan : stade puis obstacles, en DEUX pop-up successives — la
  // matière de l'effet miroir, posée pendant l'attente de l'analyse. La pop-up
  // n'apparaît qu'après ~2,5 s d'animation (auto-attente Playwright).
  await expect(page.getByText("Où en est ton SaaS ?")).toBeVisible();
  await page.getByRole("button", { name: /Premiers clients/ }).click();
  await page.getByRole("button", { name: "Continuer", exact: true }).click();

  await expect(page.getByText("Qu'est-ce qui te bloque le plus ?")).toBeVisible();
  await page.getByRole("button", { name: "Je suis un builder, pas un marketeur" }).click();
  await page.getByRole("button", { name: "Je lance dans le silence" }).click();
  // « Autre » : le blocage dans SES mots — il doit revenir tel quel au closing.
  await page.getByRole("button", { name: "Autre", exact: true }).click();
  await page.getByPlaceholder("Dis-le avec tes mots…").fill("Mon marché est ultra saturé");
  await page.getByRole("button", { name: "Continuer", exact: true }).click();

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
  await page.getByRole("button", { name: /Voir ce que je pourrais gagner/ }).click();

  // Les montants sont annoncés pour ce qu'ils sont : de l'ARR signé.
  await expect(page.getByText("Nouvel ARR signé par mois")).toBeVisible();
  await expect(page.locator(".onb-gain-money")).toContainText("3 600");
  // La courbe de progression est tracée sur les chiffres de la projection.
  await expect(page.locator(".onb-curve")).toBeVisible();
  await page.getByRole("button", { name: "6 000 à 25 000 € / an" }).click();
  await expect(page.locator(".onb-gain-money")).toContainText("15 000");
  await page.locator(".onb-screen").getByRole("button", { name: "Continuer", exact: true }).click();

  // (4) Aucun compteur d'audience inventé, ni dans les gains ni dans la simulation.
  await expect(page.locator(".onb-sim-grid")).not.toContainText("0 abonnés");
  await expect(page.locator(".onb-screen")).not.toContainText("aujourd'hui 0");

  // Closing : les obstacles COCHÉS reviennent en miroir, le ROI est calculé sur
  // l'ACV du palier choisi (15 000 € / 49 € ≈ 306 mois), et les engagements
  // réels (places, garantie) sont écrits.
  await page.getByRole("button", { name: /Comment on s'y prend/ }).click();
  await expect(page.getByText(/je suis un builder, pas un marketeur/)).toBeVisible();
  await expect(page.getByText(/je lance dans le silence/)).toBeVisible();
  // Le texte libre « Autre » fait partie du miroir, au même titre que les chips.
  await expect(page.getByText(/mon marché est ultra saturé/)).toBeVisible();
  await expect(page.getByText(/un seul client à ton ACV/)).toBeVisible();
  await expect(page.getByText(/comptes fondateurs par mois/)).toBeVisible();
  await expect(page.getByText(/satisfait ou remboursé/i)).toBeVisible();
  return { projectionBody: () => projectionBody, leadBody };
}

test.describe("Tunnel fondateurs SaaS (anonyme)", () => {
  test("projection en grille SaaS, sortie sur l'essai gratuit et non sur le Calendly", async ({ page }) => {
    await mockBackend(page);
    const { projectionBody, leadBody } = await reachSimulation(page);

    // La porte d'entrée a bien envoyé l'e-mail au serveur — sans ça, la capture
    // de leads serait un champ décoratif.
    expect(leadBody()).toMatchObject({ email: "lea@northstack.io" });

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

    // Écran de compte : l'e-mail de la porte d'entrée est PRÉ-REMPLI — le
    // demander deux fois serait avouer qu'on a perdu la première réponse.
    await expect(page.getByRole("heading", { name: "Crée ton compte fondateur" })).toBeVisible();
    await expect(page.getByPlaceholder("toi@ton-saas.com")).toHaveValue("lea@northstack.io");
    // Et la carte est annoncée AVANT le départ vers Stripe.
    await expect(page.getByText(/0\s?€ prélevé pendant tes 7 jours/)).toBeVisible();
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

  test("quiz fini avant l'analyse : retour à l'animation, puis avancée automatique", async ({ page }) => {
    await mockBackend(page);
    // Analyse volontairement plus lente que le quiz : le visiteur doit pouvoir
    // cliquer « Continuer » sans attendre, retomber sur l'animation, et être
    // emmené tout seul vers l'analyse quand elle aboutit. Si l'avancée
    // automatique se perdait, il resterait bloqué à jamais sur le spinner —
    // panne parfaitement silencieuse.
    await page.route("**/onboarding/draft", async (route) => {
      await new Promise((r) => setTimeout(r, 9000));
      return route.fulfill({
        json: { profile: { display_name: "Léa Fondatrice" }, preview: PREVIEW },
      });
    });

    await page.goto("/founders");
    await passGate(page);
    await page.getByPlaceholder("https://ton-saas.com").fill("https://northstack.io");
    await page.getByRole("button", { name: "Analyser" }).click();

    // Les deux pop-up se répondent SANS attendre la fin de l'analyse.
    await page.getByRole("button", { name: /Premiers clients/ }).click();
    await page.getByRole("button", { name: "Continuer", exact: true }).click();
    await page.getByRole("button", { name: "Je lance dans le silence" }).click();
    await page.getByRole("button", { name: "Continuer", exact: true }).click();

    // Retour à l'animation (l'analyse tourne encore)…
    await expect(page.locator(".onb-scan-quiz")).toHaveCount(0);
    await expect(page.locator(".onb-orb")).toBeVisible();
    // …puis l'écran d'analyse arrive TOUT SEUL quand le serveur répond.
    await expect(page.getByRole("button", { name: "Voir mon potentiel" })).toBeVisible({ timeout: 15000 });
  });

  test("projection injoignable : le tunnel mène quand même à l'essai", async ({ page }) => {
    await mockBackend(page);
    await page.route("**/onboarding/projection", (route) => route.fulfill({ status: 500, json: {} }));

    await page.goto("/founders");
    await passGate(page);
    await page.getByPlaceholder("https://ton-saas.com").fill("https://northstack.io");
    await page.getByRole("button", { name: "Analyser" }).click();
    await page.getByRole("button", { name: "Continuer", exact: true }).click();
    await page.getByRole("button", { name: "Continuer", exact: true }).click();
    await page.getByRole("button", { name: "Voir mon potentiel" }).click();
    await page.getByRole("button", { name: "Continuer", exact: true }).click();
    await page.getByRole("button", { name: "Continuer", exact: true }).click();
    await page.getByRole("button", { name: /Voir ce que je pourrais gagner/ }).click();

    // Un écran de mise en scène en panne ne doit pas coûter le prospect : on
    // atterrit sur la création de compte, pas sur un écran vide ni sur /start.
    await expect(page.getByRole("heading", { name: "Crée ton compte fondateur" })).toBeVisible();
  });
});
