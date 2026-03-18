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
