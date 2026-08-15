import { test, expect, type Page } from "@playwright/test";

/**
 * Tunnel d'essai builders (/onboarding, alias /founders, parcours anonyme) :
 * landing de vente (SaaS + freelance) → site OU LinkedIn → scan (quiz
 * stade+obstacles UNIQUEMENT si entrée par le site — pas sur un profil LinkedIn)
 * → audit léger → questions → gains en ARR → simulation → UN seul écran
 * compte+plan (−40 %) → essai.
 *
 * Backend entièrement mocké (zéro coût Apify/Claude/Stripe). Ce spec verrouille les
 * écarts qui feraient de ce tunnel une copie ratée de /start, tous invisibles
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
 * 5. Plan + compte sont UN seul écran (témoignage + offre −40 % + formulaire).
 *    Un paywall intermédiaire à re-cliquer après la simulation est une page de trop.
 * 6. Le MÊME champ accepte aussi une page LinkedIn (pas d'onglet séparé) : un
 *    lien `linkedin.com/in/…` doit partir en `linkedin_url`/`use_apify_linkedin`
 *    (jamais en `website_url`), SANS quiz « Où en es-tu aujourd'hui ? », et l'écran
 *    d'analyse doit alors montrer les VRAIS compteurs lus.
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

// Entrée par une page LinkedIn : le scrape de profil renvoie de vrais
// compteurs — c'est ce qui doit apparaître à l'écran au lieu du badge « site ».
const PREVIEW_LINKEDIN = {
  handle: "lea-fondatrice",
  name: "Léa Fondatrice",
  headline: "Fondatrice @ Northstack — analytics produit pour équipes SaaS B2B",
  avatar_url: "https://media.licdn.com/dms/image/avatar-lea.jpg",
  posts_count: 8,
  followers: 1850,
  connections: 520,
  niche: "Analytics produit pour équipes SaaS B2B",
  summary: "Premier paragraphe.\n\nDeuxième paragraphe.",
  hook: "Tu parles de ton produit, jamais du problème.",
  hashtags: ["#SaaS", "#ProductLed"],
  strengths: ["Ton direct", "Sujets concrets", "Bonne régularité"],
  improvements: ["Headline floue", "Pas de CTA", "Peu de preuves chiffrées"],
};

const range = (low: number, high: number) => ({ low, high });

function saasBand(key: string, label: string, revenue: [number, number], followersNow = 0) {
  return {
    key,
    label,
    deal_value: 3600,
    projection: {
      followers_now: followersNow,
      followers_after: range(followersNow + 120, followersNow + 450),
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
  await expect(page.getByText(/onboard ~\d+ builders par mois/i)).toBeVisible();
  await expect(page.getByText(/Pour les builders/i)).toBeVisible();
  await expect(page.getByText(/places limitées\. ça prend 90 secondes/i)).toBeVisible();
  await page.getByPlaceholder("toi@email.com").fill(email);
  await page.getByRole("button", { name: /vérifier ma place/i }).first().click();
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

  await page.goto("/onboarding");
  // Landing de vente d'abord : la promesse, puis la porte d'entrée e-mail
  // (rareté réelle : places/mois via FOUNDERS_MONTHLY_SEATS) qui lance l'analyse.
  await expect(page.getByRole("heading", { name: /Le LinkedIn qui remplit ton pipeline/ })).toBeVisible();
  const { leadBody } = await passGate(page);

  // Premier écran du tunnel : le lien du SaaS, pas le profil LinkedIn.
  await page.getByPlaceholder("https://ton-site.com").fill("https://northstack.io");
  await page.getByRole("button", { name: "Analyser" }).click();

  // Pendant le scan : stade puis obstacles, en DEUX pop-up successives — la
  // matière de l'effet miroir, posée pendant l'attente de l'analyse. La pop-up
  // n'apparaît qu'après ~2,5 s d'animation (auto-attente Playwright).
  await expect(page.getByText("Où en es-tu aujourd'hui ?")).toBeVisible();
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
  await expect(page.getByRole("button", { name: "Freelances & solopreneurs" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Des prestations sur-mesure" })).toBeVisible();
  await page.getByRole("button", { name: "CTO & équipes tech" }).click();
  await page.getByRole("button", { name: "Continuer", exact: true }).click();

  await expect(page.getByText("Ton secteur")).toBeVisible();
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

  // Simulation → UN seul écran compte+plan (plus de paywall intermédiaire).
  await page.getByRole("button", { name: /Continuer vers l'essai/ }).click();
  await expect(page.getByRole("heading", { name: "Crée ton compte" })).toBeVisible();
  await expect(page.getByText(/@reshape_music/)).toBeVisible();
  await expect(page.getByText(/on a passé les 4k/i)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Choisis ton plan" })).toBeVisible();
  await expect(page.getByText("Mensuel")).toBeVisible();
  await expect(page.getByText(/−40/)).toBeVisible();
  await expect(page.getByText("29,40 €")).toBeVisible();
  await expect(page.getByText(/prix réduit/i)).toBeVisible();
  await expect(page.getByText(/satisfait ou remboursé/i)).toHaveCount(0);
  // Plus de lien « retour à la présentation » en bas de l'écran compte.
  await expect(page.getByText(/retour à la présentation/i)).toHaveCount(0);
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

    // (2) Fin de tunnel : plan + compte sur le MÊME écran — l'essai, avec sa
    // durée annoncée par le serveur — et AUCUN des deux artefacts du tunnel /start.
    await expect(page.getByRole("heading", { name: "Crée ton compte" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Choisis ton plan" })).toBeVisible();
    const trialCta = page.getByRole("button", { name: /Démarrer mes 7 jours gratuits/ });
    await expect(trialCta).toBeVisible();
    await expect(page.getByRole("button", { name: /Recevoir mon audit complet gratuit/ })).toHaveCount(0);

    // Écran de compte : l'e-mail de la porte d'entrée est PRÉ-REMPLI — le
    // demander deux fois serait avouer qu'on a perdu la première réponse.
    await expect(page.getByPlaceholder("toi@email.com")).toHaveValue("lea@northstack.io");
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
    await expect(page.getByRole("heading", { name: "Crée ton compte" })).toBeVisible();

    // Rechargement : sans la réserve de réponses, le fondateur repartirait de
    // l'analyse (donc d'un scrape payant) et perdrait sa qualification.
    await page.reload();
    await expect(page.getByRole("heading", { name: "Crée ton compte" })).toBeVisible();
    await expect(page.getByText(/ICP : .*CTO & équipes tech/)).toBeVisible();
  });

  test("mots de passe différents : aucun compte n'est créé", async ({ page }) => {
    // Le verrou porte sur l'APPEL, pas sur le message affiché : un compte ouvert
    // sur un mot de passe mal tapé n'est plus rattrapable dans ce tunnel — le
    // fondateur enchaîne sur Stripe, laisse sa carte, et se retrouve enfermé
    // dehors avec pour seule issue un e-mail de réinitialisation.
    let signups = 0;
    await page.route("**/auth/v1/signup**", (route) => {
      signups += 1;
      return route.fulfill({ status: 200, json: { user: null, session: null } });
    });

    await mockBackend(page);
    await reachSimulation(page);
    await expect(page.getByRole("heading", { name: "Crée ton compte" })).toBeVisible();

    await page.getByPlaceholder("toi@email.com").fill("lea@northstack.io");
    await page.getByPlaceholder("••••••••").fill("motdepasse1");
    await page.getByPlaceholder("Retape ton mot de passe").fill("motdepasse2");
    await expect(page.getByText("Les deux mots de passe ne sont pas identiques.")).toBeVisible();

    await page.getByRole("button", { name: /Démarrer mes 7 jours gratuits/ }).click();
    await page.waitForTimeout(500);
    expect(signups).toBe(0);

    // Corrigé : le message tombe et le formulaire repart (l'inscription réelle
    // n'est pas jouée plus loin — le mock ne rend pas de session).
    await page.getByPlaceholder("Retape ton mot de passe").fill("motdepasse1");
    await expect(page.getByText("Les deux mots de passe ne sont pas identiques.")).toHaveCount(0);
    await page.getByRole("button", { name: /Démarrer mes 7 jours gratuits/ }).click();
    await expect.poll(() => signups).toBe(1);
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

    await page.goto("/onboarding");
    await passGate(page);
    await page.getByPlaceholder("https://ton-site.com").fill("https://northstack.io");
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

    await page.goto("/onboarding");
    await passGate(page);
    await page.getByPlaceholder("https://ton-site.com").fill("https://northstack.io");
    await page.getByRole("button", { name: "Analyser" }).click();
    await page.getByRole("button", { name: "Continuer", exact: true }).click();
    await page.getByRole("button", { name: "Continuer", exact: true }).click();
    await page.getByRole("button", { name: "Voir mon potentiel" }).click();
    await page.getByRole("button", { name: "Continuer", exact: true }).click();
    await page.getByRole("button", { name: "Continuer", exact: true }).click();
    await page.getByRole("button", { name: /Voir ce que je pourrais gagner/ }).click();

    // Un écran de mise en scène en panne ne doit pas coûter le prospect : on
    // atterrit sur la création de compte, pas sur un écran vide ni sur /start.
    await expect(page.getByRole("heading", { name: "Crée ton compte" })).toBeVisible();
  });

  test("un lien LinkedIn part en linkedin_url (jamais website_url) et les vrais compteurs s'affichent", async ({
    page,
  }) => {
    // Même champ que le site — pas d'onglet séparé (cf. ticket) : on colle une
    // page LinkedIn et on vérifie que la détection + le rendu suivent la SOURCE
    // réellement collée, pas l'URI /onboarding.
    let draftBody: any = null;
    await page.route("**/onboarding/draft", (route) => {
      draftBody = route.request().postDataJSON();
      return route.fulfill({
        json: {
          profile: { display_name: "Léa Fondatrice", core_offer: "Un SaaS vendu en démo" },
          preview: PREVIEW_LINKEDIN,
          sources: { description: false, linkedin_apify: true, website_summary: false },
        },
      });
    });
    await page.route("**/billing/plan", (route) =>
      route.fulfill({
        json: {
          enabled: true,
          trial_days: 7,
          plan: { credits: 1000, amount: 49, currency: "eur", interval: "month" },
        },
      }),
    );
    await page.route("**/onboarding/projection", (route) =>
      route.fulfill({
        json: {
          default_band: "smb",
          deal_label: "Ton ACV moyen (ce que rapporte un client sur 12 mois)",
          revenue_label: "Nouvel ARR signé par mois",
          bands: [saasBand("smb", "1 200 à 6 000 € / an", [3600, 14400], 1850)],
        },
      }),
    );

    await page.goto("/onboarding");
    await expect(page.getByRole("heading", { name: /Le LinkedIn qui remplit ton pipeline/ })).toBeVisible();
    await passGate(page);

    // Le même champ que le site accepte une page LinkedIn.
    await page.getByPlaceholder("https://ton-site.com").fill("https://www.linkedin.com/in/lea-fondatrice/");
    await page.getByRole("button", { name: "Analyser" }).click();

    // LinkedIn → PAS de quiz SaaS (« Où en es-tu aujourd'hui ? » n'a pas de sens sur
    // un profil perso). L'analyse doit arriver sans ces deux pop-up.
    await expect(page.getByText("Où en es-tu aujourd'hui ?")).toHaveCount(0);
    await expect(page.getByText("Qu'est-ce qui te bloque le plus ?")).toHaveCount(0);

    // Analyse : les vrais compteurs du profil scrapé, pas le badge « site ».
    await expect(page.getByRole("button", { name: "Voir mon potentiel" })).toBeVisible({ timeout: 15000 });

    // L'URL part bien en linkedin_url + Apify activé — jamais en website_url.
    expect(draftBody).toMatchObject({
      linkedin_url: "https://www.linkedin.com/in/lea-fondatrice/",
      website_url: "",
      use_apify_linkedin: true,
    });

    await expect(page.getByText("@lea-fondatrice")).toBeVisible();
    await expect(page.getByText("Analysé depuis ton site")).toHaveCount(0);
    await expect(page.getByText("Analysé depuis ta description")).toHaveCount(0);

    await page.getByRole("button", { name: "Voir mon potentiel" }).click();
    await page.getByRole("button", { name: "Continuer", exact: true }).click();
    await page.getByRole("button", { name: "Une cible précise" }).click();
    await page.getByRole("button", { name: "CTO & équipes tech" }).click();
    await page.getByRole("button", { name: "Continuer", exact: true }).click();
    await page.getByRole("button", { name: "DevTools & infra" }).click();
    await page.getByRole("button", { name: /Voir ce que je pourrais gagner/ }).click();

    // Audience réellement lue : la courbe s'ancre sur l'audience mesurée, pas
    // sur un gain à partir de zéro — et « aujourd'hui 0 » ne doit jamais
    // apparaître à quelqu'un dont le compte vient d'être lu.
    await expect(page.getByText("Abonnés dans 90 jours")).toBeVisible();
    await expect(page.locator(".onb-screen")).not.toContainText("aujourd'hui 0");
  });

  test("une page entreprise LinkedIn est refusée avec un message actionnable", async ({ page }) => {
    // linkedin.com/company/… n'est ni un site lisible (login-wall) ni un profil
    // — le refuser AVANT tout appel serveur évite l'analyse creuse silencieuse.
    let draftCalled = false;
    await page.route("**/onboarding/draft", (route) => {
      draftCalled = true;
      return route.fulfill({ json: { profile: {}, preview: null } });
    });

    await page.goto("/onboarding");
    await passGate(page);
    await page.getByPlaceholder("https://ton-site.com").fill("https://www.linkedin.com/company/northstack/");
    await page.getByRole("button", { name: "Analyser" }).click();

    await expect(page.getByText(/pages entreprise/i)).toBeVisible();
    await expect(page.getByText(/linkedin\.com\/in\//)).toBeVisible();
    expect(draftCalled).toBe(false);
  });

  test("/founders reste un alias : même landing, même tunnel", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/founders");
    await expect(page.getByRole("heading", { name: /Le LinkedIn qui remplit ton pipeline/ })).toBeVisible();
    await expect(page.getByText(/Pour les builders/i)).toBeVisible();
    await expect(page.getByText(/onboard ~\d+ builders par mois/i)).toBeVisible();
    const { leadBody } = await passGate(page);
    await expect(page.getByPlaceholder("https://ton-site.com")).toBeVisible();
    expect(leadBody()).toMatchObject({ email: "lea@northstack.io" });
  });
});
