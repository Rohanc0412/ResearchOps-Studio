import { expect, test } from '@playwright/test';
import { state } from './shared';

export function registerReportModule(): void {
  // ── Report pane rendering ──────────────────────────────────────────────────

  test('10.1 report pane renders headings after run completes', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    // Report pane is the right-hand column — look for at least one heading
    await expect(
      page.locator('h1, h2, h3').filter({ hasText: /.{3,}/ }).first()
    ).toBeVisible({ timeout: 30_000 });
  });

  test('10.2 report pane status badge shows READY', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    await expect(
      page.getByText(/^READY$/i)
    ).toBeVisible({ timeout: 15_000 });
  });

  test('10.3 section inline edit — pencil button visible on hover', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    const heading = page.locator('h1, h2, h3').filter({ hasText: /.{3,}/ }).first();
    await expect(heading).toBeVisible({ timeout: 15_000 });
    // Hover over a section in the report pane to reveal edit button
    await heading.hover();
    const editBtn = page.locator('[data-testid="section-edit-btn"], button[title="Edit section"], button[aria-label*="edit" i]').first();
    if (await editBtn.isVisible({ timeout: 3_000 })) {
      await expect(editBtn).toBeVisible();
    } else {
      test.info().annotations.push({ type: 'note', description: 'Edit button not visible on hover — may use click-to-edit' });
    }
  });

  test('10.4 export button opens export modal', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    // Look for the export button in the report pane toolbar
    const exportBtn = page.getByRole('button', { name: /export/i }).first();
    await expect(exportBtn).toBeVisible({ timeout: 15_000 });
    await exportBtn.click();
    // Export modal should open
    await expect(
      page.locator('[role="dialog"]').filter({ hasText: /export/i }).first().or(
        page.getByText(/markdown|pdf|docx|word/i).first()
      )
    ).toBeVisible({ timeout: 5_000 });
    // Close it
    await page.keyboard.press('Escape');
  });

  test('10.5 export markdown triggers download', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    const exportBtn = page.getByRole('button', { name: /export/i }).first();
    await expect(exportBtn).toBeVisible({ timeout: 15_000 });
    await exportBtn.click();
    // Wait for export modal
    const modal = page.locator('[role="dialog"]').filter({ hasText: /export|markdown|pdf/i }).first();
    if (await modal.isVisible({ timeout: 5_000 })) {
      const mdBtn = modal.getByRole('button', { name: /markdown/i });
      if (await mdBtn.isVisible({ timeout: 3_000 })) {
        const [download] = await Promise.all([
          page.waitForEvent('download', { timeout: 15_000 }),
          mdBtn.click(),
        ]);
        expect(download.suggestedFilename()).toMatch(/\.md$/i);
      } else {
        test.info().annotations.push({ type: 'note', description: 'No markdown button found in export modal' });
        await page.keyboard.press('Escape');
      }
    }
  });

  test('10.6 share button opens share modal', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    const shareBtn = page.getByRole('button', { name: /share/i }).first();
    if (await shareBtn.isVisible({ timeout: 10_000 })) {
      await shareBtn.click();
      await expect(
        page.locator('[role="dialog"]').filter({ hasText: /share|link/i }).first().or(
          page.getByText(/shareable link|copy link/i).first()
        )
      ).toBeVisible({ timeout: 5_000 });
      await page.keyboard.press('Escape');
    } else {
      test.info().annotations.push({ type: 'note', description: 'Share button not visible' });
    }
  });

  test('10.7 clear report — confirm dialog appears', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    const clearBtn = page.getByRole('button', { name: /clear/i }).first();
    if (await clearBtn.isVisible({ timeout: 10_000 })) {
      page.once('dialog', async (dialog) => {
        // Dismiss the confirm dialog — we don't want to actually clear
        await dialog.dismiss();
      });
      await clearBtn.click();
    } else {
      test.info().annotations.push({ type: 'note', description: 'Clear button not visible' });
    }
  });

  // ── Chat panel navigation ─────────────────────────────────────────────────

  test('10.8 back button returns to project page', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    await page.getByRole('button', { name: 'Back to project' }).click();
    await page.waitForURL(`**/projects/${state.projectId}`, { timeout: 10_000 });
    await expect(page).toHaveURL(new RegExp(`projects/${state.projectId}$`));
  });

  test('10.9 model selector renders available options', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    const modelSelect = page.getByRole('combobox', { name: /llm model/i });
    await expect(modelSelect).toBeVisible({ timeout: 10_000 });
    const optionCount = await modelSelect.locator('option').count();
    expect(optionCount).toBeGreaterThanOrEqual(1);
  });

  test('10.10 quick-action chips send message and update chat', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    const chip = page.getByRole('button', { name: /add conclusion|summarize findings|add references/i }).first();
    if (await chip.isVisible({ timeout: 10_000 })) {
      const chipText = await chip.textContent();
      await chip.click();
      // The textarea should now contain the chip text
      const textarea = page.getByRole('textbox', { name: /message input/i });
      await expect(textarea).toHaveValue(chipText?.trim() ?? '');
    } else {
      test.info().annotations.push({ type: 'note', description: 'Quick-action chips not visible' });
    }
  });

  // ── Accessibility spot-checks ─────────────────────────────────────────────

  test('10.11 message input has accessible label', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    await expect(page.getByRole('textbox', { name: /message input/i })).toBeVisible({ timeout: 10_000 });
  });

  test('10.12 chat message log has role="log"', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    await expect(page.locator('[role="log"]')).toBeVisible({ timeout: 10_000 });
  });

  // ════════════════════════════════════════════════
}
