import { expect, test } from '@playwright/test';
import { extractUUID, generateSafeTOTP, state, ts, waitForText } from './shared';

export function registerAuthModule(): void {
  test('1.1 register with valid credentials', async ({ page }) => {
    await page.goto('/login');
    // Switch to register mode — the toggle button is at the bottom of the login form
    await page.getByRole('button', { name: /don't have an account|create one|create account|sign up|register/i }).click();
    // Fill registration form
    await page.locator('#login-username').fill(state.user.username);
    await page.locator('#login-email').fill(state.user.email);
    await page.locator('#login-password').fill(state.user.password);
    await page.locator('#login-confirm').fill(state.user.password);
    await page.getByRole('button', { name: /^create account$/i }).click();
    // Current flow returns to login with a success banner; sign in explicitly.
    await expect(page.getByText(/account created successfully/i)).toBeVisible({ timeout: 15_000 });
    await expect(page).toHaveURL(/\/login/);
    await page.locator('#login-username').fill(state.user.username);
    await page.locator('#login-password').fill(state.user.password);
    await page.getByRole('button', { name: /^sign in$/i }).click();
    await page.waitForURL('**/projects', { timeout: 15_000 });
    await expect(page).toHaveURL(/\/projects/);
  });

  test('1.2 register duplicate email is rejected', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('button', { name: /don't have an account|create one|create account|sign up|register/i }).click();
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
    await page.getByRole('button', { name: /don't have an account|create one|create account|sign up|register/i }).click();
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
    await page.getByRole('button', { name: /don't have an account|create one|create account|sign up|register/i }).click();
    await page.locator('#login-username').fill(`short${ts}`);
    await page.locator('#login-email').fill(`short${ts}@example.com`);
    await page.locator('#login-password').fill('abc');
    await page.locator('#login-confirm').fill('abc');
    await page.getByRole('button', { name: /^create account$/i }).click();
    await expect(page.getByRole('alert').or(page.locator('[class*="error" i]')).first()).toBeVisible({ timeout: 10_000 });
    await expect(page).not.toHaveURL(/\/projects/);
  });

  test('1.5 logout redirects to login', async ({ page }) => {
    await page.goto('/login');
    await page.locator('#login-username').fill(state.user.username);
    await page.locator('#login-password').fill(state.user.password);
    await page.getByRole('button', { name: /^sign in$/i }).click();
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

  test.skip('1.9 forgot password shows success message', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('button', { name: /forgot/i }).click();
    await page.locator('#forgot-email').fill(state.user.email);
    await page.getByRole('button', { name: /send|reset/i }).click();
    // After submit the app transitions to reset mode ("Set new password") or shows a success banner
    await expect(
      page.getByText(/set new password/i).or(page.getByText(/reset token generated|if the account exists/i)).first()
    ).toBeVisible({ timeout: 15_000 });
  });

  test.skip('1.10 MFA enroll start — QR and secret rendered', async ({ page }) => {
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

  test.skip('1.11 MFA verify enroll succeeds', async ({ page }) => {
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
    if (!state.mfaSecret) {
      test.skip(true, 'mfaSecret not captured — test 1.10 must have failed');
      return;
    }
    const code = await generateSafeTOTP(state.mfaSecret);
    await page.locator('input[placeholder="123456"]').first().fill(code);
    await page.getByRole('button', { name: /verify|enable|confirm/i }).click();
    await expect(page.getByText(/enabled|active|mfa is on/i)).toBeVisible({ timeout: 10_000 });
  });

  test.skip('1.12 MFA disable succeeds', async ({ page }) => {
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

}
