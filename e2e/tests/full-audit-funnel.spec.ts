import { test, expect, type Page } from "@playwright/test";

/**
 * Tunnel « audit complet gratuit » (/start, parcours anonyme) :
 * analyse légère → gains → simulation avant/après → formulaire → Calendly.
 *
 * Backend entièrement mocké (zéro coût Apify/Claude/Resend). Le point verrouillé
 * ici — comme pour le wizard et l'autopilote — est que les données PARTENT BIEN
 * TOUTES au serveur : un lead sans téléphone ou un audit généré sans la preview
 * seraient des pannes silencieuses (e-mail générique, lead injoignable).
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

async function mockDraft(page: Page) {
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

async function reachLeadForm(page: Page) {
  await page.goto("/start");
  await page.getByPlaceholder("https://linkedin.com/in/ton-profil")
    .fill("https://linkedin.com/in/camille-dupont");
  await page.getByRole("button", { name: "Analyser" }).click();

  // Analyse légère (écran 1) puis détail (écran 2).
  await page.getByRole("button", { name: "Voir mon potentiel" }).click();
  await page.getByRole("button", { name: /Ce que tu peux gagner/ }).click();

  // Gains : fourchettes prudentes, jamais des promesses fermes.
  await expect(page.getByText("pas une promesse", { exact: false }).first()).toBeVisible();
  await page.getByRole("button", { name: /Voir mon profil dans 90 jours/ }).click();

  // Simulation : étiquetée comme telle + projection ancrée sur les VRAIS abonnés
  // scrapés (1200 → 1620), jamais un chiffre sorti de nulle part.
  await expect(page.locator(".onb-sim-tag")).toHaveText("Simulation");
  await expect(page.locator(".onb-sim-stat")).toContainText("1.6K");
  await expect(page.locator(".onb-sim-stat")).toContainText("aujourd'hui 1.2K");
  await page.getByRole("button", { name: /Recevoir mon audit complet gratuit/ }).click();
}

test.describe("Tunnel audit complet (anonyme)", () => {
  test("le lead complet part au serveur puis redirection Calendly annoncée", async ({ page }) => {
    await mockDraft(page);

    let leadBody: any = null;
    await page.route("**/onboarding/full-audit", (route) => {
      leadBody = route.request().postDataJSON();
      return route.fulfill({ json: { ok: true, email_enabled: true } });
    });
    // La confirmation redirige vers Calendly après ~4,5 s : on neutralise la
    // navigation externe pour garder la page sous contrôle du test.
    await page.route("https://calendly.com/**", (route) =>
      route.fulfill({ contentType: "text/html", body: "<html>calendly</html>" }),
    );

    await reachLeadForm(page);

    // Les 3 champs sont OBLIGATOIRES : vide ⇒ erreur, aucun appel serveur.
    await page.getByRole("button", { name: /Recevoir mon audit complet gratuit/ }).click();
    await expect(page.getByText("Les trois champs sont obligatoires", { exact: false })).toBeVisible();
    expect(leadBody).toBeNull();

    // Le nom est pré-rempli depuis l'analyse ; e-mail + téléphone saisis.
    await expect(page.getByPlaceholder("Ton nom et prénom")).toHaveValue("Camille Dupont");
    await page.getByPlaceholder("toi@exemple.com").fill("camille@exemple.com");
    await page.getByPlaceholder("06 12 34 56 78").fill("06 12 34 56 78");
    await page.getByRole("button", { name: /Recevoir mon audit complet gratuit/ }).click();

    // Confirmation : l'audit arrive PAR E-MAIL + départ Calendly annoncé.
    await expect(page.getByText("C'est noté !")).toBeVisible();
    await expect(page.getByText("par e-mail", { exact: false })).toBeVisible();
    await expect(page.getByRole("link", { name: /Choisir mon créneau maintenant/ }))
      .toHaveAttribute("href", "https://calendly.com/tom-clareo-solutions/15min");

    // Le payload porte TOUT : identité joignable + snapshot de l'analyse (sans
    // lui, l'audit par e-mail serait générique — panne silencieuse).
    expect(leadBody.name).toBe("Camille Dupont");
    expect(leadBody.email).toBe("camille@exemple.com");
    expect(leadBody.phone).toContain("06");
    expect(leadBody.linkedin_url).toContain("linkedin.com/in/camille-dupont");
    expect(leadBody.preview?.niche).toBe(PREVIEW.niche);
    expect(leadBody.profile?.display_name).toBe("Camille Dupont");
  });

  test("erreur serveur : le visiteur reste sur le formulaire avec un message", async ({ page }) => {
    await mockDraft(page);
    await page.route("**/onboarding/full-audit", (route) =>
      route.fulfill({ status: 400, json: { detail: "Cet e-mail ne semble pas valide." } }),
    );

    await reachLeadForm(page);
    await page.getByPlaceholder("toi@exemple.com").fill("pas-un-email");
    await page.getByPlaceholder("06 12 34 56 78").fill("0612345678");
    await page.getByRole("button", { name: /Recevoir mon audit complet gratuit/ }).click();

    await expect(page.getByText("Cet e-mail ne semble pas valide.")).toBeVisible();
    // Toujours sur le formulaire — pas de fausse confirmation.
    await expect(page.getByPlaceholder("toi@exemple.com")).toBeVisible();
  });
});
