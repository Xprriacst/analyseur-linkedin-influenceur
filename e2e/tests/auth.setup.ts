import { test as setup } from "@playwright/test";
import { login } from "./helpers";

const authFile = "playwright/.auth/user.json";

// Authentifie une fois et persiste la session pour les tests "authenticated".
setup("authenticate", async ({ page }) => {
  await login(page);
  await page.context().storageState({ path: authFile });
});
