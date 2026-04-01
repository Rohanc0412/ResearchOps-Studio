import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetchJson } from "../../../api/client";
import { buildFinalResponse } from "../lib/reportArtifacts";
import { extractReportTitle, parseMarkdownToSections } from "../lib/reportParser";
import { loadStoredReport, persistReport } from "../lib/reportStorage";
import { EMPTY_REPORT } from "../constants";
import type { Report } from "../types";
import type { Artifact } from "../../../types/dto";
import { ArtifactSchema } from "../../../types/dto";
import { z } from "zod";

const ArtifactsSchema = z.array(ArtifactSchema);

export function useReportHydration(chatId: string | undefined) {
  const [report, setReport] = useState<Report>(EMPTY_REPORT);
  const [highlightedSection, setHighlightedSection] = useState<string | null>(null);
  const [completedRunArtifacts, setCompletedRunArtifacts] = useState<Record<string, Artifact[]>>({});

  const reportChatIdRef = useRef<string | null>(null);
  const highlightTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset state when chatId changes and load persisted report
  useEffect(() => {
    if (!chatId) {
      reportChatIdRef.current = null;
      setReport(EMPTY_REPORT);
      setCompletedRunArtifacts({});
      return;
    }
    const stored = loadStoredReport(chatId);
    reportChatIdRef.current = chatId;
    setReport(stored ?? EMPTY_REPORT);
    setCompletedRunArtifacts({});
  }, [chatId]);

  // Persist report whenever it changes
  useEffect(() => {
    if (!chatId) return;
    if (reportChatIdRef.current !== chatId) return;
    persistReport(chatId, report);
  }, [chatId, report]);

  // Clean up highlight timeout on unmount
  useEffect(() => {
    return () => {
      if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current);
    };
  }, []);

  const hydrateReportFromArtifacts = useCallback(
    async (runId: string, targetChatId: string | null = chatId ?? null) => {
      const artifacts = await apiFetchJson(`/runs/${encodeURIComponent(runId)}/artifacts`, {
        schema: ArtifactsSchema,
      }).catch(() => [] as Artifact[]);

      if (artifacts.length > 0) {
        setCompletedRunArtifacts((prev) => ({ ...prev, [runId]: artifacts }));
      }

      const response = buildFinalResponse(artifacts);
      if (!response || response === "Run completed. Output is available in artifacts.") return;

      const parsedSections = parseMarkdownToSections(response);
      if (parsedSections.length === 0) return;

      if (targetChatId && reportChatIdRef.current !== targetChatId) return;

      const parsedTitle = extractReportTitle(response);
      setReport((prev) => ({
        ...prev,
        title: parsedTitle ?? prev.title,
        sections: parsedSections,
      }));

      const firstSection = parsedSections[0];
      if (firstSection) {
        setHighlightedSection(firstSection.id);
        if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current);
        highlightTimeoutRef.current = setTimeout(() => setHighlightedSection(null), 2000);
      }
    },
    [chatId],
  );

  function clearReport() {
    setReport(EMPTY_REPORT);
    if (chatId) {
      persistReport(chatId, EMPTY_REPORT);
    }
  }

  return {
    report,
    setReport,
    highlightedSection,
    completedRunArtifacts,
    setCompletedRunArtifacts,
    hydrateReportFromArtifacts,
    clearReport,
  };
}
