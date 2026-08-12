import { test, expect, type Page } from "@playwright/test";

/**
 * Tunnel « audit complet gratuit » (/start, parcours anonyme) :
 * audit léger → questions → gains projetés → simulation 90 jours → formulaire → Calendly.
 *
 * Backend entièrement mocké (zéro coût Apify/Claude/Resend). Ce que le spec
 * verrouille, ce sont les deux endroits où une panne serait TOTALEMENT silencieuse :
 *
 * 1. La projection doit partir avec les VRAIS chiffres du scrape. Envoyer des zéros
 *    donnerait un écran de gains d'apparence normale, mais générique — la promesse
 *    commerciale ne serait plus celle du prospect qui la lit.
 * 2. Le lead doit partir COMPLET (identité joignable + preview + profil + projection
 *    affichée). Perdre la projection en route, c'est envoyer par e-mail un audit qui
 *    contredit les chiffres montrés à l'écran, sans la moindre erreur nulle part.
 */

const PREVIEW = {
  handle: "camille-dupont",
  name: "Camille Dupont",
  headline: "Consultante growth B2B",
  avatar_url: "",
  posts_count: 10,
  followers: 1200,
  connections: 800,
  niche: "Consultante growth pour PME industrielles",
  summary: "Premier paragraphe.\n\nDeuxième paragraphe.",
  hook: "Tu postes sans framework clair.",
  hashtags: ["#Growth", "#B2B"],
  strengths: ["Ton direct", "Sujets concrets", "Bonne régularité"],
  improvements: ["Headline floue", "Pas de CTA", "Peu de preuves chiffrées"],
};

const range = (low: number, high: number) => ({ low, high });

function bandPayload(key: string, label: string, revenue: [number, number]) {
  return {
    key,
    label,
    deal_value: 3000,
    projection: {
      followers_now: 1200,
      followers_after: range(1420, 1860),
      followers_gain: range(220, 660),
      relations_per_month: range(40, 110),
      conversations_per_month: range(5, 20),
      clients_per_month: range(1, 4),
      revenue_per_month: range(revenue[0], revenue[1]),
    },
    assumptions: [`Panier moyen retenu : ${label}.`],
  };
}

async function mockBackend(page: Page) {
  await page.route("**/onboarding/draft", (route) =>
    route.fulfill({
      json: {
        profile: { display_name: "Camille Dupont", target_audience: "Dirigeants de PME" },
        preview: PREVIEW,
        sources: { description: false, linkedin_apify: true, website_summary: false },
      },
    }),
  );
}

/** Va de la landing jusqu'au formulaire de lead, en renvoyant le corps reçu par la projection. */
async function reachLeadForm(page: Page): Promise<{ projectionBody: () => any }> {
  let projectionBody: any = null;
  await page.route("**/onboarding/projection", (route) => {
    projectionBody = route.request().postDataJSON();
    return route.fulfill({
      json: {
        default_band: "mid",
        bands: [
          bandPayload("small", "Moins de 1 000 €", [1200, 4800]),
          bandPayload("mid", "1 000 à 5 000 €", [6000, 24000]),
          bandPayload("high", "5 000 à 20 000 €", [24000, 96000]),
        ],
      },
    });
  });

  await page.goto("/start");
  await page.getByPlaceholder("https://linkedin.com/in/ton-profil")
    .fill("https://linkedin.com/in/camille-dupont");
  await page.getByRole("button", { name: "Analyser" }).click();

  // Audit léger (écran 1) puis son détail (écran 2).
  await page.getByRole("button", { name: "Voir mon potentiel" }).click();
  await page.getByRole("button", { name: "Continuer", exact: true }).click();
  // Questions de qualification (page1 → page2), pré-remplies par l'analyse.
  await expect(page.getByPlaceholder("Ton nom et prénom")).toHaveValue("Camille Dupont");
  await page.getByRole("button", { name: "Continuer", exact: true }).click();
  await page.getByRole("button", { name: /Voir ce que je pourrais gagner/ }).click();

  // Gains : le CA affiché suit le palier de panier moyen choisi (c'est le levier
  // de l'écran — s'il ne bougeait pas, la personnalisation serait décorative).
  await expect(page.locator(".onb-gain-money")).toContainText("6 000");
  await page.getByRole("button", { name: "5 000 à 20 000 €" }).click();
  await expect(page.locator(".onb-gain-money")).toContainText("24 000");
  // Le CTA des gains est un « Continuer » générique : on le cible dans son écran
  // pour ne pas le confondre avec ceux des écrans de questions précédents.
  await page.locator(".onb-screen").getByRole("button", { name: "Continuer", exact: true }).click();

  // Simulation : ancrée sur les vrais abonnés scrapés (1 200 aujourd'hui).
  await expect(page.locator(".onb-sim-grid")).toContainText("1 200");
  await page.getByRole("button", { name: /Recevoir mon audit complet gratuit/ }).click();

  // Le formulaire demande un téléphone : l'aperçu de ce qu'on reçoit doit être là,
  // sections lisibles et contenu flouté (sans lui, on demande sans rien montrer).
  await expect(page.locator(".onb-doc")).toBeVisible();
  await expect(page.locator(".onb-doc-section-title").first()).toHaveText("Diagnostic de ton profil");

  return { projectionBody: () => projectionBody };
}

test.describe("Tunnel audit complet (anonyme)", () => {
  test("projection ancrée sur le scrape, lead complet au serveur, puis Calendly", async ({ page }) => {
    await mockBackend(page);

    let leadBody: any = null;
    await page.route("**/onboarding/audit-lead", (route) => {
      leadBody = route.request().postDataJSON();
      return route.fulfill({
        json: { ok: true, calendly_url: "https://calendly.com/tom-clareo-solutions/15min" },
      });
    });
    // La confirmation redirige vers Calendly après ~4 s : on neutralise la
    // navigation externe pour garder la page sous contrôle du test.
    await page.route("https://calendly.com/**", (route) =>
      route.fulfill({ contentType: "text/html", body: "<html>calendly</html>" }),
    );

    const { projectionBody } = await reachLeadForm(page);

    // (1) La projection a bien été demandée sur les chiffres réels du profil.
    expect(projectionBody()).toMatchObject({ followers: 1200, connections: 800, posts_count: 10 });

    // Les 3 champs sont obligatoires : vides ⇒ erreur, aucun appel serveur.
    await page.getByRole("button", { name: /Recevoir mon audit gratuit/ }).click();
    await expect(page.getByText("Indique ton nom et prénom.")).toBeVisible();
    expect(leadBody).toBeNull();

    await page.getByPlaceholder("Camille Durand").fill("Camille Dupont");
    await page.getByPlaceholder("camille@exemple.com").fill("camille@exemple.com");
    await page.getByPlaceholder("06 12 34 56 78").fill("06 12 34 56 78");
    await page.getByRole("button", { name: /Recevoir mon audit gratuit/ }).click();

    // Confirmation : l'audit arrive PAR E-MAIL + départ Calendly proposé.
    await expect(page.getByText("C'est envoyé")).toBeVisible();
    await expect(page.getByText("arrive par e-mail", { exact: false })).toBeVisible();
    await expect(page.getByRole("link", { name: /Choisir mon créneau/ }))
      .toHaveAttribute("href", "https://calendly.com/tom-clareo-solutions/15min");

    // (2) Le payload porte TOUT : identité joignable, ce qui a été analysé, et la
    // projection réellement affichée (celle du palier choisi, pas celle par défaut).
    expect(leadBody.full_name).toBe("Camille Dupont");
    expect(leadBody.email).toBe("camille@exemple.com");
    expect(leadBody.phone).toContain("06");
    expect(leadBody.input_kind).toBe("linkedin");
    expect(leadBody.linkedin_url).toContain("linkedin.com/in/camille-dupont");
    expect(leadBody.preview?.niche).toBe(PREVIEW.niche);
    expect(leadBody.profile?.display_name).toBe("Camille Dupont");
    expect(leadBody.projection?.revenue_per_month?.low).toBe(24000);
  });

  test("erreur serveur : le visiteur reste sur le formulaire, sans fausse confirmation", async ({ page }) => {
    await mockBackend(page);
    await page.route("**/onboarding/audit-lead", (route) =>
      route.fulfill({ status: 400, json: { detail: "Cet e-mail ne semble pas valide." } }),
    );

    await reachLeadForm(page);
    await page.getByPlaceholder("Camille Durand").fill("Camille Dupont");
    await page.getByPlaceholder("camille@exemple.com").fill("camille@exemple.com");
    await page.getByPlaceholder("06 12 34 56 78").fill("0612345678");
    await page.getByRole("button", { name: /Recevoir mon audit gratuit/ }).click();

    await expect(page.getByText("Cet e-mail ne semble pas valide.")).toBeVisible();
    await expect(page.getByText("C'est envoyé")).toHaveCount(0);
    await expect(page.getByPlaceholder("camille@exemple.com")).toBeVisible();
  });
});
