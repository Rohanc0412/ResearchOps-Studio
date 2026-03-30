import { expect, test } from '@playwright/test';
import { extractUUID, generateSafeTOTP, state, waitForText } from './shared';

export function registerEvidenceModule(): void {
  test('7.1 navigate to snippet detail', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await page.getByRole('button', { name: /^evidence$/i }).click();
    const snippetLink = page.locator('a[href*="/evidence/snippets/"]').first();
    if (await snippetLink.isVisible({ timeout: 10_000 })) {
      const href = await snippetLink.getAttribute('href') ?? '';
      state.snippetId = extractUUID(href);
      await snippetLink.click();
      await page.waitForURL('**/evidence/snippets/**', { timeout: 10_000 });
      await expect(page).toHaveURL(/evidence\/snippets/);
    } else {
      test.info().annotations.push({ type: 'note', description: 'No snippet links found — run may have no evidence' });
    }
  });

  test('7.2 snippet detail shows text content', async ({ page }) => {
    if (!state.snippetId) {
      test.skip(true, 'No snippetId available — Module 7.1 found no snippets');
      return;
    }
    await page.goto(`/evidence/snippets/${state.snippetId}`);
    await page.waitForURL(`**/evidence/snippets/${state.snippetId}`, { timeout: 10_000 });
    await expect(page.locator('h1, h2, [class*="title" i]').first()).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('p, [class*="text" i]').first()).toBeVisible({ timeout: 5_000 });
  });

  test('7.3 external source link present', async ({ page }) => {
    if (!state.snippetId) {
      test.skip(true, 'No snippetId available');
      return;
    }
    await page.goto(`/evidence/snippets/${state.snippetId}`);
    await page.waitForURL(`**/evidence/snippets/${state.snippetId}`, { timeout: 10_000 });
    const externalLink = page.locator('a[target="_blank"]').first();
    if (await externalLink.isVisible()) {
      const href = await externalLink.getAttribute('href');
      expect(href).toMatch(/^https?:\/\//);
    }
  });

  test('7.4 non-existent snippet shows 404', async ({ page }) => {
    await page.goto('/evidence/snippets/00000000-0000-0000-0000-000000000000');
    await expect(
      page.getByText(/not found|does not exist/i).first()
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByRole('link', { name: /back to projects/i }).or(
        page.getByRole('button', { name: /back/i })
      ).first()
    ).toBeVisible({ timeout: 5_000 });
  });

  test('7.5 back to projects link from 404 navigates to /projects', async ({ page }) => {
    await page.goto('/evidence/snippets/00000000-0000-0000-0000-000000000000');
    await page.waitForURL('**/evidence/snippets/00000000-0000-0000-0000-000000000000', { timeout: 10_000 });
    const backLink = page.getByRole('link', { name: /back to projects/i });
    await expect(backLink).toBeVisible({ timeout: 10_000 });
    await backLink.click();
    await page.waitForURL('**/projects', { timeout: 10_000 });
    await expect(page).toHaveURL(/\/projects/);
  });

  // ════════════════════════════════════════════════

}
