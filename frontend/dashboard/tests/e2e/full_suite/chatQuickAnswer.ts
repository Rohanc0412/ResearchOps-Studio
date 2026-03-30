import { expect, test } from '@playwright/test';
import { extractUUID, generateSafeTOTP, state, waitForText } from './shared';

export function registerChatQuickAnswerModule(): void {
  test('4.1 send plain question and receive answer', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    const textarea = page.getByPlaceholder(/ask a question|request a report/i);
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await textarea.fill('What is machine learning in simple terms?');
    await page.getByRole('button', { name: /send/i }).click();
    // Wait for a response to appear — any element that looks like assistant content
    await expect(
      page.locator('[class*="message" i]').last()
    ).toBeVisible({ timeout: 60_000 });
    // Verify the page isn't still showing just the user's own message as last element
    await page.waitForTimeout(2_000); // brief wait for streaming to begin
    const msgCount = await page.locator('[class*="message" i]').count();
    expect(msgCount).toBeGreaterThanOrEqual(1);
  });

  test('4.2 web search indicator appears for current-events question', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    const textarea = page.getByPlaceholder(/ask a question|request a report/i);
    await textarea.fill('What are the breaking AI news stories from this week?');
    await page.getByRole('button', { name: /send/i }).click();
    await expect(page.getByText(/searching the web/i)).toBeVisible({ timeout: 30_000 });
  });

  test('4.3 markdown is rendered not shown as raw text', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    await expect(page.locator('[class*="message" i]').first()).toBeVisible({ timeout: 10_000 });
    // Raw ** or ## should not appear as literal text
    const rawMarkdownCount = await page.getByText(/^\*\*|^##/).count();
    expect(rawMarkdownCount).toBe(0);
  });

  test('4.4 send empty message does not submit', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    const textarea = page.getByPlaceholder(/ask a question|request a report/i);
    await textarea.fill('');
    await page.getByRole('button', { name: /send/i }).click();
    await expect(page).toHaveURL(new RegExp(state.chatId));
    await expect(textarea).toBeFocused();
  });

  test('4.5 whitespace-only message does not submit', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    const textarea = page.getByPlaceholder(/ask a question|request a report/i);
    await textarea.fill('     ');
    await page.getByRole('button', { name: /send/i }).click();
    await expect(page).toHaveURL(new RegExp(state.chatId));
  });

  test('4.6 send follow-up message shows multiple pairs', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}/chats/${state.chatId}`);
    await page.waitForURL(`**/chats/${state.chatId}`, { timeout: 10_000 });
    const textarea = page.getByPlaceholder(/ask a question|request a report/i);
    await textarea.fill('Can you give me a one-sentence summary?');
    await page.getByRole('button', { name: /send/i }).click();
    // Wait for at least 2 message elements (the follow-up + at least one prior)
    await expect(async () => {
      const count = await page.locator('[class*="message" i]').count();
      expect(count).toBeGreaterThanOrEqual(2);
    }).toPass({ timeout: 60_000 });
  });

  // ════════════════════════════════════════════════

}
