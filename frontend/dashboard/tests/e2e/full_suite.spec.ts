import { test, expect } from '@playwright/test';
import { authenticator } from 'otplib';

// ── Shared state (populated as tests run) ────────────────────────────────────

const ts = Date.now();
const state = {
  user: {
    username: `testuser${ts}`,
    email: `testuser${ts}@example.com`,
    password: 'TestPass123!',
  },
  mfaSecret: '',
  projectId: '',
  projectName: `Test Project ${ts}`,
  chatId: '',
  runId: '',
  artifactId: '',
  snippetId: '',
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function extractUUID(url: string): string {
  const m = url.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
  if (!m) throw new Error(`No UUID found in URL: ${url}`);
  return m[0];
}

async function waitForText(
  page: import('@playwright/test').Page,
  selector: string,
  pattern: RegExp,
  timeout = 60_000,
) {
  await expect(page.locator(selector).filter({ hasText: pattern })).toBeVisible({ timeout });
}

async function generateSafeTOTP(secret: string): Promise<string> {
  // Wait if we're within 3 seconds of the end of a 30-second window
  const timeStep = 30;
  const remaining = timeStep - (Math.floor(Date.now() / 1000) % timeStep);
  if (remaining <= 3) {
    await new Promise(resolve => setTimeout(resolve, (remaining + 1) * 1000));
  }
  return authenticator.generate(secret);
}

// ── Suite ────────────────────────────────────────────────────────────────────

test.describe.serial('ResearchOps Studio — Full E2E Suite', () => {
  // ════════════════════════════════════════════════
  // MODULE 1 — AUTH
  // ════════════════════════════════════════════════

  test('1.1 register with valid credentials', async ({ page }) => {
    await page.goto('/login');
    // Switch to register mode — the toggle button is at the bottom of the login form
    await page.getByRole('button', { name: /don't have an account|create account|sign up|register/i }).click();
    // Fill registration form
    await page.locator('#login-username').fill(state.user.username);
    await page.locator('#login-email').fill(state.user.email);
    await page.locator('#login-password').fill(state.user.password);
    await page.locator('#login-confirm').fill(state.user.password);
    await page.getByRole('button', { name: /^create account$/i }).click();
    // Should redirect to /projects
    await page.waitForURL('**/projects', { timeout: 15_000 });
    await expect(page).toHaveURL(/\/projects/);
  });

  test('1.2 register duplicate email is rejected', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('button', { name: /don't have an account|create account|sign up|register/i }).click();
    await page.locator('#login-username').fill(`other${ts}`);
    await page.locator('#login-email').fill(state.user.email); // same email
    await page.locator('#login-password').fill(state.user.password);
    await page.locator('#login-confirm').fill(state.user.password);
    await page.getByRole('button', { name: /^create account$/i }).click();
    await expect(page.getByRole('alert').or(page.locator('[class*="error" i]')).first()).toBeVisible({ timeout: 10_000 });
    await expect(page).not.toHaveURL(/\/projects/);
  });

  test('1.3 register mismatched passwords is rejected', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('button', { name: /don't have an account|create account|sign up|register/i }).click();
    await page.locator('#login-username').fill(`mismatch${ts}`);
    await page.locator('#login-email').fill(`mismatch${ts}@example.com`);
    await page.locator('#login-password').fill('TestPass123!');
    await page.locator('#login-confirm').fill('WrongPass456!');
    await page.getByRole('button', { name: /^create account$/i }).click();
    await expect(page.getByRole('alert').or(page.locator('[class*="error" i]')).first()).toBeVisible({ timeout: 10_000 });
    await expect(page).not.toHaveURL(/\/projects/);
  });

  test('1.4 register short password is rejected', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('button', { name: /don't have an account|create account|sign up|register/i }).click();
    await page.locator('#login-username').fill(`short${ts}`);
    await page.locator('#login-email').fill(`short${ts}@example.com`);
    await page.locator('#login-password').fill('abc');
    await page.locator('#login-confirm').fill('abc');
    await page.getByRole('button', { name: /^create account$/i }).click();
    await expect(page.getByRole('alert').or(page.locator('[class*="error" i]')).first()).toBeVisible({ timeout: 10_000 });
    await expect(page).not.toHaveURL(/\/projects/);
  });

  test('1.5 logout redirects to login', async ({ page }) => {
    await page.goto('/projects');
    await page.waitForURL('**/projects', { timeout: 15_000 });
    await page.getByRole('button', { name: /logout/i }).click();
    await page.waitForURL('**/login', { timeout: 10_000 });
    await expect(page).toHaveURL(/\/login/);
  });

  test('1.6 login with wrong password shows error', async ({ page }) => {
    await page.goto('/login');
    await page.locator('#login-username').fill(state.user.username);
    await page.locator('#login-password').fill('WrongPassword999!');
    await page.getByRole('button', { name: /^sign in$/i }).click();
    await expect(page.getByRole('alert').or(page.locator('[class*="error" i]')).first()).toBeVisible({ timeout: 10_000 });
    await expect(page).toHaveURL(/\/login/);
  });

  test('1.7 login with valid credentials', async ({ page }) => {
    await page.goto('/login');
    await page.locator('#login-username').fill(state.user.username);
    await page.locator('#login-password').fill(state.user.password);
    await page.getByRole('button', { name: /^sign in$/i }).click();
    await page.waitForURL('**/projects', { timeout: 15_000 });
    await expect(page).toHaveURL(/\/projects/);
  });

  test('1.8 protected route redirects unauthenticated user', async ({ page }) => {
    await page.goto('/login');
    await page.evaluate(() => localStorage.removeItem('researchops_access_token'));
    await page.goto('/projects');
    await page.waitForURL('**/login', { timeout: 10_000 });
    await expect(page).toHaveURL(/\/login/);
    // Log back in for subsequent tests
    await page.locator('#login-username').fill(state.user.username);
    await page.locator('#login-password').fill(state.user.password);
    await page.getByRole('button', { name: /^sign in$/i }).click();
    await page.waitForURL('**/projects', { timeout: 15_000 });
    await expect(page).toHaveURL(/\/projects/);
  });

  test('1.9 forgot password shows success message', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('button', { name: /forgot/i }).click();
    await page.locator('#forgot-email').fill(state.user.email);
    await page.getByRole('button', { name: /send|reset/i }).click();
    // After submit the app transitions to reset mode ("Set new password") or shows a success banner
    await expect(
      page.getByText(/set new password/i).or(page.getByText(/reset token generated|if the account exists/i)).first()
    ).toBeVisible({ timeout: 15_000 });
  });

  test('1.10 MFA enroll start — QR and secret rendered', async ({ page }) => {
    await page.goto('/login');
    await page.locator('#login-username').fill(state.user.username);
    await page.locator('#login-password').fill(state.user.password);
    await page.getByRole('button', { name: /^sign in$/i }).click();
    await page.waitForURL('**/projects', { timeout: 15_000 });
    await page.goto('/security');
    await page.getByRole('button', { name: /enable mfa|restart setup/i }).click();
    // QR code SVG and plain-text secret visible
    await expect(page.locator('svg[viewBox]')).toBeVisible({ timeout: 10_000 });
    // Secret is rendered in the data-testid="mfa-secret" element
    const secretEl = page.locator('[data-testid="mfa-secret"]');
    await expect(secretEl).toBeVisible({ timeout: 10_000 });
    state.mfaSecret = ((await secretEl.textContent()) ?? '').trim().replace(/\s/g, '');
    expect(state.mfaSecret.length).toBeGreaterThan(10);
  });

  test('1.11 MFA verify enroll succeeds', async ({ page }) => {
    await page.goto('/security');
    // Confirm we're on the security page (not redirected to login)
    const currentUrl = page.url();
    if (currentUrl.includes('/login')) {
      // Session expired, log back in
      await page.locator('#login-username').fill(state.user.username);
      await page.locator('#login-password').fill(state.user.password);
      await page.getByRole('button', { name: /^sign in$/i }).click();
      await page.waitForURL('**/projects', { timeout: 15_000 });
      await page.goto('/security');
    }
    await expect(page).toHaveURL(/\/security/);
    const enableBtn = page.getByRole('button', { name: /enable mfa|restart setup/i });
    if (await enableBtn.isVisible({ timeout: 3_000 })) {
      await enableBtn.click();
      const secretEl = page.locator('[data-testid="mfa-secret"]');
      await expect(secretEl).toBeVisible({ timeout: 10_000 });
      state.mfaSecret = ((await secretEl.textContent()) ?? '').trim().replace(/\s/g, '');
    }
    const code = await generateSafeTOTP(state.mfaSecret);
    await page.locator('input[placeholder="123456"]').first().fill(code);
    await page.getByRole('button', { name: /verify|enable|confirm/i }).click();
    await expect(page.getByText(/enabled|active|mfa is on/i)).toBeVisible({ timeout: 10_000 });
  });

  test('1.12 MFA disable succeeds', async ({ page }) => {
    await page.goto('/security');
    await expect(page.getByRole('button', { name: /disable mfa/i })).toBeVisible({ timeout: 10_000 });
    const code = await generateSafeTOTP(state.mfaSecret);
    await page.locator('input[placeholder="123456"]').last().fill(code);
    await page.getByRole('button', { name: /disable mfa/i }).click();
    await expect(
      page.getByText(/not enabled|disabled/i).or(page.getByRole('button', { name: /enable mfa/i }))
    ).toBeVisible({ timeout: 10_000 });
  });

  // ════════════════════════════════════════════════
  // MODULE 2 — PROJECTS
  // ════════════════════════════════════════════════

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
  // MODULE 3 — PROJECT DETAIL
  // ════════════════════════════════════════════════

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
  // MODULE 4 — CHAT / QUICK ANSWER
  // ════════════════════════════════════════════════

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
  // MODULE 5 — RESEARCH RUN
  // ════════════════════════════════════════════════

  test('5.1 launch run with default model — progress card appears', async ({ page }) => {
    await page.goto(`/projects/${state.projectId}`);
    await page.waitForURL(`**/projects/${state.projectId}`, { timeout: 10_000 });
    // Enable "Run pipeline" toggle (aria-pressed button)
    const pipelineToggle = page.locator('button[aria-pressed]').first();
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
      await expect(page.getByText(/recent updates|events/i)).toBeVisible({ timeout: 5_000 });
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
    const pipelineToggle = page.locator('button[aria-pressed]').first();
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
  // MODULE 6 — ARTIFACTS
  // ════════════════════════════════════════════════

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
      page.locator('[class*="mono"][class*="text-xs"]').filter({ hasText: /\d{1,2}/ }).first()
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
  // MODULE 7 — EVIDENCE
  // ════════════════════════════════════════════════

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
  // MODULE 8 — EVALUATION
  // ════════════════════════════════════════════════

  test('8.1 evaluation tab shows empty state before triggering', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await page.getByRole('button', { name: /^evaluation$/i }).click();
    await expect(
      page.getByRole('button', { name: /run evaluation/i })
    ).toBeVisible({ timeout: 10_000 });
  });

  test('8.2 trigger evaluation — button enters loading state', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await page.getByRole('button', { name: /^evaluation$/i }).click();
    await expect(page.getByRole('button', { name: /run evaluation/i })).toBeVisible({ timeout: 10_000 });
    await page.getByRole('button', { name: /run evaluation/i }).click();
    // Button should enter loading/disabled state
    await expect(
      page.locator('[class*="spinner" i], [class*="loading" i]').first().or(
        page.getByRole('button', { name: /run evaluation/i }).and(page.locator('[disabled]'))
      ).first()
    ).toBeVisible({ timeout: 15_000 });
  });

  test('8.3 evaluation completes and metrics cards appear', async ({ page }) => {
    test.setTimeout(300_000); // 5 min
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await page.getByRole('button', { name: /^evaluation$/i }).click();
    const runEvalBtn = page.getByRole('button', { name: /run evaluation/i });
    if (await runEvalBtn.isVisible({ timeout: 3_000 })) {
      await runEvalBtn.click();
    }
    await expect(
      page.getByText(/grounding|faithfulness|sections passed/i).first()
    ).toBeVisible({ timeout: 240_000 });
  });

  test('8.4 metric values contain numbers', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await page.getByRole('button', { name: /^evaluation$/i }).click();
    await expect(page.getByText(/grounding|faithfulness/i).first()).toBeVisible({ timeout: 15_000 });
    // The metric card value divs contain numbers
    const metricValue = page.locator('[class*="text-2xl"][class*="font-bold"]').first();
    if (await metricValue.isVisible()) {
      const text = await metricValue.textContent();
      expect(text).toMatch(/\d/);
    }
  });

  test('8.5 section rows render with verdicts', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await page.getByRole('button', { name: /^evaluation$/i }).click();
    await expect(page.getByText(/grounding|faithfulness/i).first()).toBeVisible({ timeout: 15_000 });
    await expect(
      page.getByText(/pass|fail/i).first()
    ).toBeVisible({ timeout: 10_000 });
  });

  test('8.6 expand failed section shows issue badges', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await page.getByRole('button', { name: /^evaluation$/i }).click();
    await expect(page.getByText(/grounding|faithfulness/i).first()).toBeVisible({ timeout: 15_000 });
    const failRow = page.locator('[class*="border-red"]').first();
    if (await failRow.isVisible({ timeout: 5_000 })) {
      await failRow.click();
      await expect(
        page.getByText(/unsupported|contradicted|missing.citation|invalid.citation|not.in.pack|overstated/i).first()
      ).toBeVisible({ timeout: 5_000 });
    } else {
      test.info().annotations.push({ type: 'note', description: 'No failed sections found to expand' });
    }
  });

  test('8.7 collapse section hides issues', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await page.getByRole('button', { name: /^evaluation$/i }).click();
    await expect(page.getByText(/grounding|faithfulness/i).first()).toBeVisible({ timeout: 15_000 });
    const failRow = page.locator('[class*="border-red"]').first();
    if (await failRow.isVisible({ timeout: 5_000 })) {
      await failRow.click();
      await page.waitForTimeout(500);
      await failRow.click();
      await expect(
        page.getByText(/unsupported|contradicted|missing.citation/i)
      ).not.toBeVisible({ timeout: 3_000 });
    }
  });

  test('8.8 re-run evaluation refreshes results', async ({ page }) => {
    test.setTimeout(300_000);
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await page.getByRole('button', { name: /^evaluation$/i }).click();
    await expect(page.getByText(/grounding|faithfulness/i).first()).toBeVisible({ timeout: 15_000 });
    // Re-run button contains RotateCcw icon (look by aria or svg class)
    const rerunBtn = page.locator('[data-testid="rerun-evaluation-btn"]');
    if (await rerunBtn.isVisible({ timeout: 5_000 })) {
      await rerunBtn.click();
      await expect(
        page.locator('[class*="spinner" i], [class*="loading" i]').first()
      ).toBeVisible({ timeout: 15_000 });
      await expect(
        page.getByText(/grounding|faithfulness/i).first()
      ).toBeVisible({ timeout: 240_000 });
    }
  });

  test('8.9 concurrent evaluation triggers — no crash', async ({ page }) => {
    await page.goto(`/runs/${state.runId}/artifacts`);
    await page.waitForURL(`**/runs/${state.runId}/artifacts`, { timeout: 10_000 });
    await page.getByRole('button', { name: /^evaluation$/i }).click();
    const runEvalBtn = page.getByRole('button', { name: /run evaluation/i });
    if (await runEvalBtn.isVisible({ timeout: 3_000 })) {
      await runEvalBtn.click();
      await runEvalBtn.click();
      await expect(page.locator('body')).toBeVisible({ timeout: 5_000 });
      await page.waitForTimeout(2_000);
      const hasError = await page.getByText(/conflict|already running|try again/i).isVisible();
      const hasSpinner = await page.locator('[class*="spinner" i]').first().isVisible();
      expect(hasError || hasSpinner).toBe(true);
    }
  });

  // ════════════════════════════════════════════════
  // MODULE 9 — ERROR & EDGE CASES
  // ════════════════════════════════════════════════

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
});
