import type { Report } from "../types";

function reportStorageKey(chatId: string): string {
  return `researchops_report:${chatId}`;
}

function isReportLike(value: unknown): value is Report {
  if (!value || typeof value !== "object") return false;
  const report = value as Report;
  if (typeof report.title !== "string" || !Array.isArray(report.sections)) return false;
  return report.sections.every((section) => {
    if (!section || typeof section !== "object") return false;
    if (typeof section.id !== "string" || typeof section.heading !== "string") return false;
    if (!Array.isArray(section.content)) return false;
    return section.content.every((item) => item && typeof item.text === "string");
  });
}

export function loadStoredReport(chatId: string): Report | null {
  try {
    const raw = window.localStorage.getItem(reportStorageKey(chatId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    return isReportLike(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function clearedRunStorageKey(chatId: string): string {
  return `researchops_cleared_run:${chatId}`;
}

/** Record that the user explicitly cleared the report for a given run. */
export function markReportCleared(chatId: string, runId: string): void {
  try {
    window.localStorage.setItem(clearedRunStorageKey(chatId), runId);
  } catch { /* ignore */ }
}

/** Return the runId the user last cleared, or null if they haven't. */
export function getClearedRunId(chatId: string): string | null {
  try {
    return window.localStorage.getItem(clearedRunStorageKey(chatId));
  } catch { return null; }
}

export function persistReport(chatId: string, report: Report): void {
  try {
    const key = reportStorageKey(chatId);
    if (report.sections.length === 0) {
      window.localStorage.removeItem(key);
      return;
    }
    window.localStorage.setItem(key, JSON.stringify(report));
  } catch {
    // Ignore storage failures in the browser.
  }
}
