import { expect, test } from "@playwright/test";

test("removing the stored access token logs the user out of protected routes", async ({ page }) => {
  const ts = Date.now();
  const username = `protectedroute${ts}`;
  const email = `protectedroute${ts}@example.com`;
  const password = "TestPass123!";

  await page.goto("/login");
  await page.getByRole("button", { name: /create one|create account|sign up|register/i }).click();
  await page.locator("#login-username").fill(username);
  await page.locator("#login-email").fill(email);
  await page.locator("#login-password").fill(password);
  await page.locator("#login-confirm").fill(password);
  await page.getByRole("button", { name: /^create account$/i }).click();
  await expect(page.getByText(/account created successfully/i)).toBeVisible({ timeout: 15_000 });

  await page.locator("#login-username").fill(username);
  await page.locator("#login-password").fill(password);
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page.waitForURL("**/projects", { timeout: 15_000 });
  await expect(page.getByRole("button", { name: /logout/i })).toBeVisible({ timeout: 15_000 });

  await page.evaluate(() => localStorage.removeItem("researchops_access_token"));
  await page.goto("/projects");

  await expect(page.getByRole("heading", { name: /welcome back/i })).toBeVisible({ timeout: 10_000 });
  await expect(page).toHaveURL(/\/login/);
});
