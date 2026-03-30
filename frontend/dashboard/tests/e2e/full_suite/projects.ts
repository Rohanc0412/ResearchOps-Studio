import { expect, test } from '@playwright/test';
import { extractUUID, generateSafeTOTP, state, ts, waitForText } from './shared';

export function registerProjectsModule(): void {
  test('2.1 create project with name and description', async ({ page }) => {
    await page.goto('/projects');
    await page.waitForURL('**/projects', { timeout: 15_000 });
    await page.getByRole('button', { name: /new project|\+ new/i }).click();
    await expect(page.locator('[role="dialog"]').first()).toBeVisible({ timeout: 5_000 });
    await page.getByPlaceholder(/e\.g\. Market|project name/i).fill(state.projectName);
    await page.getByPlaceholder(/description|about this project/i).fill('Automated E2E test project');
    await page.getByRole('button', { name: /^create$/i }).click();
    await expect(page.getByText(state.projectName)).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[role="dialog"]')).not.toBeVisible({ timeout: 5_000 });
  });

  test('2.2 create project without name is rejected', async ({ page }) => {
    await page.goto('/projects');
    await page.getByRole('button', { name: /new project|\+ new/i }).click();
    await expect(page.locator('[role="dialog"]').first()).toBeVisible({ timeout: 5_000 });
    // Leave name empty, try to submit
    await page.getByRole('button', { name: /^create$/i }).click();
    // Modal should remain open
    await expect(page.locator('[role="dialog"]').first()).toBeVisible({ timeout: 3_000 });
    // Dismiss modal
    await page.keyboard.press('Escape');
  });

  test('2.3 create project name only succeeds', async ({ page }) => {
    await page.goto('/projects');
    await page.getByRole('button', { name: /new project|\+ new/i }).click();
    const nameOnly = `NameOnly ${ts}`;
    await page.getByPlaceholder(/e\.g\. Market|project name/i).fill(nameOnly);
    await page.getByRole('button', { name: /^create$/i }).click();
    await expect(page.getByText(nameOnly)).toBeVisible({ timeout: 10_000 });
  });

  test('2.4 search projects — match filters list', async ({ page }) => {
    await page.goto('/projects');
    await page.waitForURL('**/projects', { timeout: 10_000 });
    const partial = state.projectName.slice(0, 8);
    await page.getByPlaceholder(/search projects/i).fill(partial);
    await expect(page.getByText(state.projectName)).toBeVisible({ timeout: 5_000 });
  });

  test('2.5 search projects — no match shows empty state', async ({ page }) => {
    await page.goto('/projects');
    await page.getByPlaceholder(/search projects/i).fill('zzz_no_match_xyzabc999');
    await expect(
      page.getByText(/no projects|nothing here|no results/i).or(page.locator('[class*="empty" i]').first())
    ).toBeVisible({ timeout: 5_000 });
  });

  test('2.6 clear search restores full list', async ({ page }) => {
    await page.goto('/projects');
    const searchInput = page.getByPlaceholder(/search projects/i);
    await searchInput.fill('zzz_no_match_xyzabc999');
    await searchInput.clear();
    await expect(page.getByText(state.projectName)).toBeVisible({ timeout: 5_000 });
  });

  test('2.7 navigate into project captures projectId', async ({ page }) => {
    await page.goto('/projects');
    await page.waitForURL('**/projects', { timeout: 10_000 });
    await page.getByText(state.projectName).click();
    await page.waitForURL('**/projects/**', { timeout: 10_000 });
    state.projectId = extractUUID(page.url());
    expect(state.projectId).toMatch(/[0-9a-f-]{36}/);
  });

  // ════════════════════════════════════════════════

}
