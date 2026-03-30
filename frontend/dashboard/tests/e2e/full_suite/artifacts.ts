import { expect, test } from '@playwright/test';
import { extractUUID, generateSafeTOTP, state, waitForText } from './shared';

export function registerArtifactsModule(): void {
  test('6.1 navigate to artifacts page from chat', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    const artifactsLink = page.locator('a[aria-label="View all artifacts"]').or(
      page.locator('a').filter({ hasText: /view artifacts/i })
    ).first();
    await expect(artifactsLink).toBeVisible({ timeout: 30_000 });
    await artifactsLink.click();
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await expect(page).toHaveURL(new RegExp(state.runId));
  });

  test('6.2 artifacts tab is default and shows artifact', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await expect(page.getByRole('button', { name: /^artifacts$/i })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/report/i).first()).toBeVisible({ timeout: 10_000 });
  });

  test('6.3 artifact shows type label and timestamp', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    // Type badge (e.g. "report_md") in mono font
    await expect(page.locator('[class*="mono"]').filter({ hasText: /report/i }).first()).toBeVisible({ timeout: 10_000 });
    // Timestamp — formatTs renders a date string like "Jan 1" or "Mar 29" next to the artifact
    await expect(
      page.locator('[data-testid="artifact-timestamp"]').first()
    ).toBeVisible({ timeout: 5_000 });
  });

  test('6.4 preview artifact opens markdown panel', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await page.locator('button[title="Preview"]').first().click();
    await expect(
      page.locator('[class*="prose" i]').first().or(page.locator('[class*="preview" i]').first())
    ).toBeVisible({ timeout: 5_000 });
  });

  test('6.5 download artifact triggers file download', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.locator('button[title="Download"]').first().click(),
    ]);
    expect(download.suggestedFilename()).toBeTruthy();
  });

  test('6.6 evidence tab shows snippets', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await page.getByRole('button', { name: /^evidence$/i }).click();
    await expect(
      page.locator('a[href*="/evidence/snippets/"]').first().or(
        page.getByText(/no snippets|no evidence/i).first()
      )
    ).toBeVisible({ timeout: 10_000 });
    // Capture snippetId if available
    const snippetLink = page.locator('a[href*="/evidence/snippets/"]').first();
    if (await snippetLink.isVisible()) {
      const href = await snippetLink.getAttribute('href') ?? '';
      state.snippetId = extractUUID(href);
    }
  });

  test('6.7 evaluation tab shows empty state', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await page.getByRole('button', { name: /^evaluation$/i }).click();
    await expect(
      page.getByRole('button', { name: /run evaluation/i })
    ).toBeVisible({ timeout: 10_000 });
  });

  test('6.8 back navigation returns to previous page', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await page.getByRole('button', { name: /back/i }).click();
    await expect(page).not.toHaveURL(new RegExp(`runs/${state.runId}/artifacts`));
  });

  test('6.9 focus query param auto-previews artifact', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    // Fetch artifact list via API to get a valid artifactId
    const resp = await page.request.get(`/api/runs/${state.runId}/artifacts`);
    if (resp.ok()) {
      const data = await resp.json() as Array<{ id: string }>;
      if (data.length > 0) {
        state.artifactId = data[0]!.id;
        await page.goto(`/runs/${state.runId}/artifacts?focus=${state.artifactId}`);
        await page.waitForURL(`**/artifacts?focus=${state.artifactId}`, { timeout: 10_000 });
        await expect(
          page.locator('[class*="prose" i]').first().or(page.locator('[class*="preview" i]').first())
        ).toBeVisible({ timeout: 10_000 });
      }
    }
  });

  // ════════════════════════════════════════════════

}
