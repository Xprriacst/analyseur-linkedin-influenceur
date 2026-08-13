import { test, expect } from "@playwright/test";
import { gotoTab } from "./helpers";

// Backlog Notion « Intégrer l'agent IA dans l'inbox » (option A) : depuis une
// conversation de l'Inbox (LinkedIn ou Instagram), un bouton « Demander à
// l'Assistant » bascule sur l'onglet Agent IA avec un message de contexte
// pré-rempli (nom du contact + derniers messages) — même patron que `onRework`
// (Générateur/Mes contenus → Agent IA), mais depuis l'Inbox plutôt qu'un post.
// LECTURE SEULE côté Inbox (aucun envoi de message) ; l'appel `/chat` déclenché
// par l'auto-envoi du contexte est MOCKÉ (zéro coût Anthropic).

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("Inbox LinkedIn : « Demander à l'Assistant » ouvre l'Agent IA avec le contexte de la conversation", async ({ page }) => {
  // Compte LinkedIn de prospection connecté, avec une conversation.
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
  // Pas de conversation Instagram : n'interfère pas avec la liste unifiée.
  await page.route("**/me/ig/conversations", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify([]) })
  );

  // Agent IA : conversation vide au départ, `/chat` mocké (zéro coût réel).
  await page.route("**/chat/conversations", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
    }
    return route.fallback();
  });
  let capturedChatBody: { conversation_id?: string | null; message?: string } | null = null;
  await page.route("**/chat", (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    capturedChatBody = route.request().postDataJSON();
    const sse =
      `event: meta\ndata: {"conversation_id":"conv-e2e-inbox-ai","credits":950}\n\n` +
      `event: delta\ndata: {"text":"Voici une suggestion de réponse."}\n\n` +
      `event: done\ndata: {}\n\n`;
    return route.fulfill({ contentType: "text/event-stream", body: sse });
  });

  await gotoTab(page, "Inbox");
  await expect(page.getByText("Conversations", { exact: false }).first()).toBeVisible();
  await page.getByRole("button", { name: /Camille Dupont/ }).click();
  // Attendre le fil chargé (dernier message) avant de cliquer « Demander à
  // l'Assistant » — sinon le contexte serait construit sur des messages
  // pas encore arrivés (course entre le montage et le fetch mocké).
  await expect(page.getByText("Vous avez un tarif dégressif ?")).toBeVisible();

  const askButton = page.getByRole("button", { name: /Demander à l'Assistant/ });
  await expect(askButton).toBeVisible();
  await askButton.click();

  // Bascule sur l'Agent IA (même mécanisme que onRework : view + assistantSeed).
  await expect(page.locator(".nav-item.active", { hasText: "Agent IA" })).toBeVisible();

  // Le message pré-rempli porte le nom du contact + les derniers messages
  // échangés — assez pour demander "aide-moi à répondre" sans tout retaper.
  const userMessage = page.locator(".assistant-message.user").first();
  await expect(userMessage).toBeVisible();
  await expect(userMessage).toContainText("Camille Dupont");
  await expect(userMessage).toContainText("Vous avez un tarif dégressif ?");

  // La requête envoyée au serveur porte bien ce même contexte (pas perdu en route).
  await expect.poll(() => capturedChatBody?.message).toContain("Camille Dupont");
  expect(capturedChatBody?.message).toContain("Vous avez un tarif dégressif ?");
});
