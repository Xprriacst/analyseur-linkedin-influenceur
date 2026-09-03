import { test, expect } from "@playwright/test";

/**
 * Porte d'entrée de l'app pour un compte CONNECTÉ.
 *
 * Fichier séparé à dessein : `authenticated.spec.ts` force le mode Expert dans
 * son `beforeEach`, et c'est exactement la condition qui MASQUE le bug ci-dessous
 * (vérifié : en mode Expert la course ne se joue pas, la boucle n'apparaît pas).
 * Ce test doit tourner sur le mode par défaut, celui de tous les comptes.
 */
test("un compte connecté entre dans l'app, jamais renvoyé sur la landing", async ({ page }) => {
  // Garde-fou de la redirection des visiteurs vers `/pilote` : Supabase restaure
  // la session de façon ASYNCHRONE. Sans attendre ce verdict, l'app renvoie un
  // utilisateur connecté sur `/pilote`, qui le renvoie aussitôt dans l'app parce
  // qu'il a une session… qui repart sur `/pilote` : boucle INFINIE, l'app devient
  // inaccessible sans la moindre erreur à l'écran.
  //
  // ⚠️ Vérifier l'URL finale ne suffit pas (elle est bonne à chaque aller-retour) :
  // on enregistre les changements d'historique. Vérifié par la négative — en
  // retirant le garde `sessionChecked`, ce test tombe sur `/pilote` dans navLog.
  await page.addInitScript(() => {
    const log: string[] = [];
    (window as unknown as { __navLog: string[] }).__navLog = log;
    const push = history.pushState.bind(history);
    const replace = history.replaceState.bind(history);
    history.pushState = (d, t, u) => { log.push(String(u ?? location.pathname)); return push(d, t, u as string); };
    history.replaceState = (d, t, u) => { log.push(String(u ?? location.pathname)); return replace(d, t, u as string); };
  });

  await page.goto("/");
  // Mode Pilote (défaut) ou vue Expert selon le compte : les deux sont « dans l'app ».
  await expect(page.locator(".pilot-app-layout, .app-shell").first()).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(3_000); // laisse le temps à une éventuelle boucle de se déclarer
  expect(new URL(page.url()).pathname).toBe("/");

  const nav = await page.evaluate(() => (window as unknown as { __navLog: string[] }).__navLog);
  expect(nav.filter((u) => u.includes("/pilote"))).toEqual([]);
});
