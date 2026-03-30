import { expect, test } from '@playwright/test';
import { extractUUID, generateSafeTOTP, state, waitForText } from './shared';

export function registerProjectDetailModule(): void {
  test('3.1 project detail shows empty conversations state', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}`);
    await page.waitForURL(`**/projects/${state.projectId}`, { timeout: 10_000 });
    await expect(
      page.getByText(/no conversations|start a new|no chats|begin/i).or(
        page.locator('[class*="empty" i]').first()
      )
    ).toBeVisible({ timeout: 10_000 });
  });

  test('3.2 create conversation via compose box', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}`);
    await page.waitForURL(`**/projects/${state.projectId}`, { timeout: 10_000 });
    const compose = page.getByPlaceholder(/ask a question|request a report|research topic/i);
    await expect(compose).toBeVisible({ timeout: 10_000 });
    await compose.fill('What are the latest advances in transformer models?');
    await page.keyboard.press('Enter');
    await page.waitForURL(`**/projects/${state.projectId}/chats/**`, { timeout: 15_000 });
    const chatSegment = page.url().split('/chats/')[1] ?? '';
    state.chatId = extractUUID(chatSegment);
    expect(state.chatId).toMatch(/[0-9a-f-]{36}/);
  });

  test('3.3 create conversation via New Chat button', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}`);
    await page.waitForURL(`**/projects/${state.projectId}`, { timeout: 10_000 });
    await page.getByRole('button', { name: /new chat/i }).click();
    await page.waitForURL(`**/projects/${state.projectId}/chats/**`, { timeout: 15_000 });
    const compose = page.getByPlaceholder(/ask a question|request a report/i);
    await expect(compose).toBeVisible({ timeout: 5_000 });
  });

  test('3.4 project detail lists recent chats', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}`);
    await page.waitForURL(`**/projects/${state.projectId}`, { timeout: 10_000 });
    // The chat from 3.2 should appear
    await expect(
      page.getByText(/What are the latest advances|Untitled/i)
    ).toBeVisible({ timeout: 10_000 });
  });

  test('3.5 open existing chat navigates correctly', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}`);
    await page.waitForURL(`**/projects/${state.projectId}`, { timeout: 10_000 });
    // Click a chat row that links to our chatId
    const chatLink = page.locator(`a[href*="${state.chatId}"]`).first();
    if (await chatLink.isVisible({ timeout: 5_000 })) {
      await chatLink.click();
    } else {
      await page.getByText(/What are the latest advances|Untitled/i).first().click();
    }
    await page.waitForURL('**/chats/**', { timeout: 10_000 });
    expect(page.url()).toContain(state.chatId);
  });

  // ════════════════════════════════════════════════

}
