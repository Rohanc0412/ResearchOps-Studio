import { expect, test } from '@playwright/test';
import { extractUUID, generateSafeTOTP, state, waitForText } from './shared';

export function registerEvaluationModule(): void {
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
        page.getByRole('button', { name: /run evaluation/i }).and(page.locator(':disabled'))
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

}
