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

// ── Suite ────────────────────────────────────────────────────────────────────

test.describe.serial('ResearchOps Studio — Full E2E Suite', () => {
  // Modules will be added below
});
