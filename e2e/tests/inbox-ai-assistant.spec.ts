import { test, expect } from "@playwright/test";
import { gotoTab } from "./helpers";

// Backlog Notion « Intégrer l'agent IA dans l'inbox » : en vue agence, l'onglet
// Agent IA DISPARAÎT — l'assistant devient une conversation de l'Inbox, dans la
// même liste que les prospects, avec un filtre « Tout / Prospects / Assistant ».
//
// Ce spec verrouille les TROIS portes d'entrée, parce qu'aucune ne signale sa
// panne à l'écran : depuis un prospect, depuis un post (« Retravailler avec
// l'Agent IA ») et à froid (« + Assistant »). Si l'une se perd dans un refacto,
// l'utilisateur n'a plus aucun moyen de joindre l'assistant — l'onglet, lui,
// n'existe plus pour rattraper.
//
// LECTURE SEULE côté Inbox (aucun message envoyé à un prospect) ; l'appel `/chat`
// est MOCKÉ par un flux SSE fabriqué → zéro coût Anthropic réel.

type ChatBody = { conversation_id?: string | null; message?: string };

/** Backend mocké commun : 1 conversation LinkedIn, 1 Instagram, `/chat` en SSE. */
async function mockInbox(page: import("@playwright/test").Page) {
  const captured: ChatBody[] = [];

  await page.route("**/me/linkedin/outreach/status", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        configured: true,
        connected: true,
        account_name: "Compte de test",
        connected_at: "2026-08-01T09:00:00Z",
        quota: {
          daily_cap: 25,
          weekly_invite_cap: 100,
          invites_today: 0,
          messages_today: 0,
          invites_week: 0,
          can_invite: true,
          can_message: true,
        },
      }),
    })
  );
  await page.route("**/me/linkedin/outreach/chats", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          chats: [
            {
              id: "chat-e2e-inbox-ai",
              name: "Camille Dupont",
              last_message_at: "2026-08-13T10:00:00Z",
              provider_url: "https://www.linkedin.com/in/camille-dupont-e2e",
            },
          ],
        }),
      });
    }
    return route.fallback();
  });
  await page.route("**/me/linkedin/outreach/chats/chat-e2e-inbox-ai/messages", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        messages: [
          { id: "m1", text: "Bonjour, votre offre m'intéresse.", from_me: false, created_at: "2026-08-13T09:00:00Z" },
          { id: "m2", text: "Avec plaisir, je vous envoie le détail.", from_me: true, created_at: "2026-08-13T09:05:00Z" },
          { id: "m3", text: "Vous avez un tarif dégressif ?", from_me: false, created_at: "2026-08-13T10:00:00Z" },
        ],
      }),
    })
  );
  await page.route("**/me/ig/conversations", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "ig-e2e-inbox-ai",
          prospect_id: "insta_prospect",
          prospect_name: "Léa Martin",
          mode: "supervised",
          last_message_at: "2026-08-13T08:00:00Z",
        },
      ]),
    })
  );
  // ⚠️ Le fil IG renvoie un TABLEAU nu (pas `{messages: […]}` comme LinkedIn), et
  // le composant charge messages + brouillons en parallèle : sans le second mock,
  // l'appel part sur le vrai backend.
  await page.route("**/me/ig/conversations/ig-e2e-inbox-ai/messages", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        { id: "im1", text: "Salut, c'est quoi vos tarifs ?", role: "in", created_at: "2026-08-13T08:00:00Z" },
      ]),
    })
  );
  await page.route("**/me/ig/conversations/ig-e2e-inbox-ai/drafts", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify([]) })
  );

  // Historique des conversations de l'Assistant : vide au départ.
  await page.route("**/chat/conversations", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
    }
    return route.fallback();
  });
  await page.route("**/chat", (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    captured.push(route.request().postDataJSON());
    const sse =
      `event: meta\ndata: {"conversation_id":"conv-e2e-inbox-ai","credits":950}\n\n` +
      `event: delta\ndata: {"text":"Voici une suggestion de réponse."}\n\n` +
      `event: done\ndata: {}\n\n`;
    return route.fulfill({ contentType: "text/event-stream", body: sse });
  });

  return captured;
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("L'onglet Agent IA a disparu de la navigation agence", async ({ page }) => {
  await mockInbox(page);
  await gotoTab(page, "Inbox");
  // L'assistant vit dans l'Inbox : plus d'entrée de navigation qui lui soit propre.
  await expect(page.locator(".nav-item", { hasText: /^Agent IA$/ })).toHaveCount(0);
});

test("Depuis un prospect LinkedIn : « Demander à l'Assistant » ouvre un fil DANS l'Inbox, avec le contexte", async ({ page }) => {
  const captured = await mockInbox(page);

  await gotoTab(page, "Inbox");
  await page.getByRole("button", { name: /Camille Dupont/ }).click();
  // Attendre le fil chargé (dernier message) avant de cliquer : sinon le contexte
  // serait construit sur des messages pas encore arrivés.
  await expect(page.getByText("Vous avez un tarif dégressif ?")).toBeVisible();

  await page.getByRole("button", { name: /Demander à l'Assistant/ }).click();

  // On RESTE dans l'Inbox — c'est tout le sujet du lot.
  await expect(page.locator(".nav-item.active", { hasText: "Inbox" })).toBeVisible();

  // Le contexte pré-rempli porte le nom du contact + les derniers messages.
  const userMessage = page.locator(".assistant-message.user").first();
  await expect(userMessage).toBeVisible();
  await expect(userMessage).toContainText("Camille Dupont");
  await expect(userMessage).toContainText("Vous avez un tarif dégressif ?");

  // Et il part bien au serveur (une perte en route donnerait un assistant qui
  // répond hors sujet, sans la moindre erreur visible).
  await expect.poll(() => captured[0]?.message).toContain("Camille Dupont");
  expect(captured[0]?.message).toContain("Vous avez un tarif dégressif ?");
});

test("Depuis un prospect Instagram : le même bouton ouvre un fil avec le contexte du DM", async ({ page }) => {
  const captured = await mockInbox(page);

  await gotoTab(page, "Inbox");
  await page.getByRole("button", { name: /Léa Martin/ }).click();
  await expect(page.getByText("Salut, c'est quoi vos tarifs ?").first()).toBeVisible();

  await page.getByRole("button", { name: /Demander à l'Assistant/ }).click();

  await expect(page.locator(".nav-item.active", { hasText: "Inbox" })).toBeVisible();
  await expect.poll(() => captured[0]?.message).toContain("Léa Martin");
  expect(captured[0]?.message).toContain("Salut, c'est quoi vos tarifs ?");
});

test("À froid : « + Assistant » démarre une conversation sans passer par un prospect", async ({ page }) => {
  const captured = await mockInbox(page);

  await gotoTab(page, "Inbox");
  await page.getByRole("button", { name: /^\+?\s*Assistant$/ }).first().click();

  // Une ligne apparaît dans la liste pour le fil en cours de création : sans
  // elle, le volet droit afficherait une conversation que la liste ignore.
  await expect(page.getByRole("button", { name: /Nouvelle conversation/ })).toBeVisible();

  const composer = page.locator(".assistant-composer textarea");
  await expect(composer).toBeVisible();
  await composer.fill("Donne-moi 3 idées de posts sur le recrutement.");
  await page.getByRole("button", { name: /^Envoyer$/ }).click();

  await expect.poll(() => captured[0]?.message).toContain("3 idées de posts");
  // Fil neuf : aucune conversation existante n'est réutilisée.
  expect(captured[0]?.conversation_id ?? null).toBeNull();
});

test("Le rafraîchissement automatique de la liste ne coupe pas une réponse en cours", async ({ page }) => {
  // ⚠️ Le piège central du déménagement : la liste de l'Inbox se recharge seule
  // (6 s côté Instagram). Si un rafraîchissement remonte le fil de l'Assistant,
  // il coupe le flux SSE en pleine écriture — panne intermittente, invisible sur
  // un mock instantané. On répond donc DÉLIBÉRÉMENT lentement (8 s), pour qu'au
  // moins un poll tombe pendant l'écriture, et on exige la réponse complète.
  await mockInbox(page);

  // La liste doit VRAIMENT bouger pendant l'écriture, sinon le test ne prouve
  // rien : chaque poll ramène un message plus récent, puis une conversation de
  // plus — donc un re-rendu et un re-tri à chaque passage.
  let poll = 0;
  await page.unroute("**/me/ig/conversations");
  await page.route("**/me/ig/conversations", (route) => {
    poll += 1;
    const convs = [
      {
        id: "ig-e2e-inbox-ai",
        prospect_id: "insta_prospect",
        prospect_name: "Léa Martin",
        mode: "supervised",
        last_message_at: new Date(Date.UTC(2026, 7, 13, 8, poll)).toISOString(),
      },
      ...(poll > 1
        ? [{ id: `ig-nouveau-${poll}`, prospect_id: "autre", prospect_name: `Nouveau prospect ${poll}`, mode: "supervised", last_message_at: new Date(Date.UTC(2026, 7, 13, 9, poll)).toISOString() }]
        : []),
    ];
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(convs) });
  });

  await page.unroute("**/chat");
  await page.route("**/chat", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    await new Promise((r) => setTimeout(r, 8000));
    return route.fulfill({
      contentType: "text/event-stream",
      body:
        `event: meta\ndata: {"conversation_id":"conv-lente","credits":900}\n\n` +
        `event: delta\ndata: {"text":"Réponse arrivée entière malgré les polls."}\n\n` +
        `event: done\ndata: {}\n\n`,
    });
  });

  await gotoTab(page, "Inbox");
  await page.getByRole("button", { name: /^\+?\s*Assistant$/ }).first().click();
  await page.locator(".assistant-composer textarea").fill("Question lente.");
  await page.getByRole("button", { name: /^Envoyer$/ }).click();

  // Témoin : la liste a bien bougé pendant l'écriture (sinon on ne testerait rien).
  await expect(page.getByRole("button", { name: /Nouveau prospect/ }).first()).toBeVisible({ timeout: 15000 });
  await expect(page.getByText("Réponse arrivée entière malgré les polls.")).toBeVisible({ timeout: 20000 });
});

test("Le filtre segmenté sépare prospects et fils de l'Assistant", async ({ page }) => {
  await mockInbox(page);

  await gotoTab(page, "Inbox");
  await expect(page.getByRole("button", { name: /Camille Dupont/ })).toBeVisible();

  // Le filtre porte `aria-pressed` — ce qui le distingue du bouton « + Assistant »
  // (même libellé) et donne un état lisible aux lecteurs d'écran.
  const filterButton = (label: string) => page.locator("button[aria-pressed]", { hasText: new RegExp(`^${label}$`) });

  // « Assistant » : les prospects sortent de la liste.
  await filterButton("Assistant").click();
  await expect(page.getByRole("button", { name: /Camille Dupont/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Léa Martin/ })).toHaveCount(0);

  // « Prospects » : ils reviennent.
  await filterButton("Prospects").click();
  await expect(page.getByRole("button", { name: /Camille Dupont/ })).toBeVisible();
});
