import { expect, test } from '@playwright/test';
import { extractUUID, generateSafeTOTP, state, waitForText } from './shared';

export function registerErrorModule(): void {
  test('9.1 unknown route renders NotFoundPage', async ({ page }) => {
    await page.goto('/this-route-absolutely-does-not-exist');
    await expect(
      page.getByText(/not found|404|page doesn't exist|page not found/i).first()
    ).toBeVisible({ timeout: 10_000 });
  });

  test('9.2 non-existent run artifacts shows error state', async ({ page }) => {
    await page.goto('/runs/00000000-0000-0000-0000-000000000000/artifacts');
    await expect(
      page.getByText(/not found|error|failed/i).first()
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('body')).not.toBeEmpty();
  });

  test('9.3 non-existent project shows error state', async ({ page }) => {
    await page.goto('/projects/00000000-0000-0000-0000-000000000000');
    await expect(
      page.getByText(/not found|error|failed/i).first()
    ).toBeVisible({ timeout: 10_000 });
  });

  test('9.4 clearing localStorage redirects to login', async ({ page }) => {
    await page.goto('/projects');
    await page.waitForURL('**/projects', { timeout: 15_000 });
    await page.evaluate(() => localStorage.removeItem('researchops_access_token'));
    await page.goto('/projects');
    await page.waitForURL('**/login', { timeout: 10_000 });
    await expect(page).toHaveURL(/\/login/);
    // Log back in
    await page.locator('#login-username').fill(state.user.username);
    await page.locator('#login-password').fill(state.user.password);
    await page.getByRole('button', { name: /^sign in$/i }).click();
    await page.waitForURL('**/projects', { timeout: 15_000 });
    await expect(page).toHaveURL(/\/projects/);
  });

  test('9.5 empty search then clear restores project list', async ({ page }) => {
    await page.goto('/projects');
    await page.waitForURL('**/projects', { timeout: 10_000 });
    const searchInput = page.getByPlaceholder(/search projects/i);
    await searchInput.fill('zzz_no_match_xyzabc');
    await expect(
      page.getByText(/no projects|nothing here|no results/i).or(page.locator('[class*="empty" i]').first())
    ).toBeVisible({ timeout: 5_000 });
    await searchInput.clear();
    await expect(page.getByText(state.projectName)).toBeVisible({ timeout: 5_000 });
  });

  test('9.6 navigate to /login while authenticated redirects to /projects', async ({ page }) => {
    await page.goto('/projects');
    await page.waitForURL('**/projects', { timeout: 15_000 });
    await expect(page).toHaveURL(/\/projects/);
    await page.goto('/login');
    await page.waitForURL('**/projects', { timeout: 10_000 });
    // Authenticated users should be redirected to /projects
    await expect(page).toHaveURL(/\/projects/, { timeout: 5_000 });
  });

}
