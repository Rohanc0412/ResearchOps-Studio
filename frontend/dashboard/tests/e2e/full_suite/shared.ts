import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';
import { authenticator } from 'otplib';

export const ts = Date.now();

export const state = {
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

export function extractUUID(url: string): string {
  const match = url.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
  if (!match) throw new Error(`No UUID found in URL: ${url}`);
  return match[0];
}

export async function waitForText(
  page: Page,
  selector: string,
  pattern: RegExp,
  timeout = 60_000,
): Promise<void> {
  await expect(page.locator(selector).filter({ hasText: pattern })).toBeVisible({ timeout });
}

export async function generateSafeTOTP(secret: string): Promise<string> {
  const timeStep = 30;
  const remaining = timeStep - (Math.floor(Date.now() / 1000) % timeStep);
  if (remaining <= 3) {
    await new Promise(resolve => setTimeout(resolve, (remaining + 1) * 1000));
  }
  return authenticator.generate(secret);
}
