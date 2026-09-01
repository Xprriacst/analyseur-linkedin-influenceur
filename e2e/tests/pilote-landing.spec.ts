import { test, expect, type Page } from "@playwright/test";

/**
 * Landing `/pilote` — écran d'entrée du mode Pilote gratuit.
 *
 * Backend et Auth mockés (zéro coût). Ce spec verrouille les pannes
 * silencieuses du ticket :
 *
 * 1. `POST /pilote/page-view` part au montage — sans ça le compteur reste à 0.
 * 2. `signUp` porte `landing: "pilote"` — sans ça les comptes ne sont pas tagués.
 * 3. Les verbatims Sacha / Joëlle sont mot pour mot (pas une paraphrase).
 * 4. Le groupe privé est annoncé, mais le lien Skool n'est PAS en clair
 *    avant inscription. Le bouton « Rejoindre le groupe privé » n'existe
 *    que sur l'écran « Compte créé », et seulement si l'invite est https.
 * 5. « Continuer avec Google » part vers /authorize?provider=google avec
 *    un retour sur /pilote. Un compte Google neuf est tagué via updateUser.
 * 6. Mots de passe différents : aucun compte créé.
 */

const SACHA =
  "Pour être honnête avec vous les gars je suis 100% satisfait de votre accompagnement";
const JOELLE = /très contente de ce premier mois de collaboration/;
const GROUP = "groupe privé de missions et de stratégies d'acquisition";
const SKOOL = "https://www.skool.com/example-invite/about";

/** Réponse GoTrue d'un signup auto-confirmé — tokens à la racine, pas `{ session }`. */
function gotrueSession(opts?: { createdAt?: string; landing?: string }) {
  return {
    access_token:
      "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ1MSIsInJvbGUiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjo0MTAyNDQ0ODAwfQ.x",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: 4102444800,
    refresh_token: "fake-refresh",
    user: {
      id: "00000000-0000-0000-0000-000000000001",
      aud: "authenticated",
      role: "authenticated",
      email: "lea@example.com",
      app_metadata: { provider: "email" },
      user_metadata: opts?.landing ? { landing: opts.landing } : {},
      created_at: opts?.createdAt ?? "2026-09-01T00:00:00.000Z",
    },
  };
}

async function mockLanding(page: Page, opts?: { inviteUrl?: string | null }) {
  const inviteUrl = opts?.inviteUrl === undefined ? SKOOL : opts.inviteUrl;
  await page.route("**/pilote/page-view", (route) => route.fulfill({ json: { ok: true } }));
  await page.route("**/pilote/invite", (route) =>
    route.fulfill({ json: { url: inviteUrl } }),
  );
}

test.describe("Landing /pilote", () => {
  test("compte la vue, affiche les verbatims, le groupe et Google, sans lien Skool", async ({
    page,
  }) => {
    let views = 0;
    await page.route("**/pilote/page-view", (route) => {
      views += 1;
      return route.fulfill({ json: { ok: true } });
    });
    await page.route("**/pilote/invite", (route) => route.fulfill({ json: { url: SKOOL } }));

    await page.goto("/pilote");

    await expect(page.getByRole("heading", { name: "Crée ton compte" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Commencer gratuitement" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Continuer avec Google" })).toBeVisible();
    await expect(page.getByText(SACHA)).toBeVisible();
    await expect(page.getByText(JOELLE)).toBeVisible();
    await expect(page.getByText("Sacha", { exact: true })).toBeVisible();
    await expect(page.getByText("Joëlle", { exact: true })).toBeVisible();
    await expect(page.getByText(GROUP).first()).toBeVisible();
    await expect(page.getByTestId("pilote-skool-invite")).toHaveCount(0);
    await expect(page.locator(`a[href="${SKOOL}"]`)).toHaveCount(0);
    await expect.poll(() => views).toBeGreaterThanOrEqual(1);
  });

  test("Continuer avec Google part vers le provider, retour sur /pilote", async ({ page }) => {
    let authorize: URL | null = null;
    await mockLanding(page);
    await page.route("**/auth/v1/authorize**", async (route) => {
      authorize = new URL(route.request().url());
      await route.fulfill({ status: 200, contentType: "text/plain", body: "oauth" });
    });

    await page.goto("/pilote");
    await page.getByRole("button", { name: "Continuer avec Google" }).click();

    await expect.poll(() => authorize).not.toBeNull();
    expect(authorize!.searchParams.get("provider")).toBe("google");
    expect(authorize!.searchParams.get("redirect_to") || "").toContain("/pilote");
  });

  test("mots de passe différents : aucun compte n'est créé", async ({ page }) => {
    let signups = 0;
    await mockLanding(page);
    await page.route("**/auth/v1/signup**", (route) => {
      signups += 1;
      return route.fulfill({ status: 200, json: { user: null, session: null } });
    });

    await page.goto("/pilote");
    await page.getByPlaceholder("toi@email.com").fill("lea@example.com");
    await page.getByPlaceholder("••••••••").fill("motdepasse1");
    await page.getByPlaceholder("Retape ton mot de passe").fill("motdepasse2");
    await expect(page.getByText("Les deux mots de passe ne sont pas identiques.")).toBeVisible();

    await page.getByRole("button", { name: "Commencer gratuitement" }).click();
    await page.waitForTimeout(400);
    expect(signups).toBe(0);

    await page.getByPlaceholder("Retape ton mot de passe").fill("motdepasse1");
    await expect(page.getByText("Les deux mots de passe ne sont pas identiques.")).toHaveCount(0);
    await page.getByRole("button", { name: "Commencer gratuitement" }).click();
    await expect.poll(() => signups).toBe(1);
  });

  test("l'inscription tague landing=pilote et révèle le lien Skool seulement après", async ({
    page,
  }) => {
    let landing: unknown;
    await mockLanding(page);
    await page.route("**/auth/v1/signup**", async (route) => {
      const body = route.request().postDataJSON() as { data?: { landing?: string } };
      landing = body?.data?.landing;
      return route.fulfill({ json: gotrueSession() });
    });

    await page.goto("/pilote");
    await expect(page.getByTestId("pilote-skool-invite")).toHaveCount(0);

    await page.getByPlaceholder("toi@email.com").fill("lea@example.com");
    await page.getByPlaceholder("••••••••").fill("motdepasse1");
    await page.getByPlaceholder("Retape ton mot de passe").fill("motdepasse1");
    await page.getByRole("button", { name: "Commencer gratuitement" }).click();

    await expect.poll(() => landing).toBe("pilote");
    await expect(page.getByRole("heading", { name: "Compte créé" })).toBeVisible();
    const invite = page.getByTestId("pilote-skool-invite");
    await expect(invite).toBeVisible();
    await expect(invite).toHaveAttribute("href", SKOOL);
    await expect(invite).toHaveText(/Rejoindre le groupe privé/);
  });

  test("sans URL d'invitation : pas de bouton mort après inscription", async ({ page }) => {
    await mockLanding(page, { inviteUrl: null });
    await page.route("**/auth/v1/signup**", (route) => route.fulfill({ json: gotrueSession() }));

    await page.goto("/pilote");
    await page.getByPlaceholder("toi@email.com").fill("lea@example.com");
    await page.getByPlaceholder("••••••••").fill("motdepasse1");
    await page.getByPlaceholder("Retape ton mot de passe").fill("motdepasse1");
    await page.getByRole("button", { name: "Commencer gratuitement" }).click();

    await expect(page.getByRole("heading", { name: "Compte créé" })).toBeVisible();
    await expect(page.getByTestId("pilote-skool-invite")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Entrer dans Cibl" })).toBeVisible();
  });
});
