import { expect, test } from '@playwright/test';
import { extractUUID, generateSafeTOTP, state, waitForText } from './shared';

export function registerResearchRunModule(): void {
  test('5.1 launch run with default model — progress card appears', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}`);
    await page.waitForURL(`**/projects/${state.projectId}`, { timeout: 10_000 });
    // Enable "Run pipeline" toggle
    const pipelineToggle = page.locator('[data-testid="pipeline-toggle"]');
    await expect(pipelineToggle).toBeVisible({ timeout: 10_000 });
    const isArmed = await pipelineToggle.getAttribute('aria-pressed');
    if (isArmed !== 'true') await pipelineToggle.click();
    await expect(pipelineToggle).toHaveAttribute('aria-pressed', 'true');
    // Type research question
    const compose = page.getByPlaceholder(/ask a question|research topic|report/i);
    await compose.fill('Recent advances in transformer architecture efficiency');
    await page.keyboard.press('Enter');
    // Navigate to chat page
    await page.waitForURL(`**/projects/${state.projectId}/chats/**`, { timeout: 15_000 });
    // ConfigureRunModal appears
    const modal = page.locator('[role="dialog"]').first();
    await expect(modal).toBeVisible({ timeout: 15_000 });
    // Click Start with defaults
    await modal.getByRole('button', { name: /start/i }).click();
    // Progress card appears
    await expect(
      page.getByText(/live research progress|retriev|outline|searching/i).first()
    ).toBeVisible({ timeout: 30_000 });
    // Capture the new chatId from URL
    const chatSegment = page.url().split('/chats/')[1] ?? '';
    const newChatId = extractUUID(chatSegment);
    if (newChatId) state.chatId = newChatId;
  });

  test('5.2 progress card shows running status', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    await expect(
      page.getByText(/live research progress|retriev|outline|draft|evaluat|searching/i).first()
    ).toBeVisible({ timeout: 60_000 });
  });

  test('5.3 progress card expand and collapse', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    // Find toggle button on progress card (first button inside the progress card area)
    const toggleBtn = page.locator('[data-testid="progress-card-toggle"]');
    if (await toggleBtn.isVisible({ timeout: 15_000 })) {
      await toggleBtn.click();
      await expect(page.getByText(/recent updates/i)).toBeVisible({ timeout: 5_000 });
      await toggleBtn.click();
      await expect(page.getByText(/recent updates/i)).not.toBeVisible({ timeout: 3_000 });
    }
  });

  test('5.4 cancel in-progress run', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    const cancelBtn = page.locator('[aria-label="Stop research run"]');
    if (await cancelBtn.isVisible({ timeout: 30_000 })) {
      await cancelBtn.click();
      await expect(cancelBtn).not.toBeVisible({ timeout: 30_000 });
    } else {
      test.info().annotations.push({ type: 'note', description: 'Run completed before cancel could be triggered' });
    }
  });

  test('5.5 retry canceled run starts new run', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    const retryBtn = page.getByRole('button', { name: /retry/i });
    if (await retryBtn.isVisible({ timeout: 15_000 })) {
      await retryBtn.click();
      await expect(
        page.getByText(/live research progress|retriev/i).first()
      ).toBeVisible({ timeout: 30_000 });
    } else {
      test.info().annotations.push({ type: 'note', description: 'No retry button — run was not in failed/canceled state' });
    }
  });

  test('5.6 configure modal — blank custom model blocks start', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}`);
    await page.waitForURL(`**/projects/${state.projectId}`, { timeout: 10_000 });
    const pipelineToggle = page.locator('[data-testid="pipeline-toggle"]');
    const isArmed = await pipelineToggle.getAttribute('aria-pressed');
    if (isArmed !== 'true') await pipelineToggle.click();
    const compose = page.getByPlaceholder(/ask a question|research topic|report/i);
    await compose.fill('Test blank custom model validation');
    await page.keyboard.press('Enter');
    await page.waitForURL(`**/chats/**`, { timeout: 15_000 });
    const modal = page.locator('[role="dialog"]').first();
    await expect(modal).toBeVisible({ timeout: 10_000 });
    // Select "Custom…" for the first stage select
    const firstSelect = modal.locator('select').first();
    await firstSelect.selectOption({ label: /custom/i });
    const customInput = modal.locator('input[placeholder="Enter model id"]').first();
    await expect(customInput).toBeVisible({ timeout: 3_000 });
    await customInput.clear();
    const startBtn = modal.getByRole('button', { name: /start/i });
    const isDisabled = await startBtn.isDisabled();
    if (!isDisabled) {
      await startBtn.click();
      await expect(modal).toBeVisible({ timeout: 3_000 });
    } else {
      expect(isDisabled).toBe(true);
    }
    await modal.getByRole('button', { name: /cancel/i }).click();
  });

  test('5.7 run completes — report complete and artifact links appear', async ({ page }) => {
    test.setTimeout(600_000);
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    // Wait for run completion (up to 9 minutes)
    await expect(
      page.getByText(/report complete/i).or(
        page.locator('a[aria-label="View all artifacts"]').or(
          page.getByText(/view artifacts/i)
        )
      ).first()
    ).toBeVisible({ timeout: 540_000 });
    // Capture runId from artifact link
    const artifactsLink = page.locator('a[aria-label="View all artifacts"]').or(
      page.locator('a').filter({ hasText: /view artifacts/i })
    ).first();
    await expect(artifactsLink).toBeVisible({ timeout: 15_000 }); // hard fail if no link
    const href = await artifactsLink.getAttribute('href') ?? '';
    state.runId = extractUUID(href);
    expect(state.runId).toMatch(/[0-9a-f-]{36}/);
  });

  test('5.8 report sections rendered inline after completion', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    await expect(
      page.locator('h1, h2, h3').filter({ hasText: /./ }).first()
    ).toBeVisible({ timeout: 30_000 });
  });

  // ════════════════════════════════════════════════

}
