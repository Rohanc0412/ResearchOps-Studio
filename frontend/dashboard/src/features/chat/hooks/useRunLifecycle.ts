import { useEffect, useRef, useState } from "react";
import { apiFetchJson } from "../../../api/client";
import { useCancelRunMutation, useRetryRunMutation } from "../../../api/runs";
import { useSSE } from "../../../hooks/useSSE";
import { buildResearchProgressCardModel } from "../../../components/run/researchProgress";
import { deriveRunUpdate } from "../lib/runUpdates";
import { CUSTOM_MODEL_VALUE } from "../constants";
import { getClearedRunId } from "../lib/reportStorage";
import type { ActiveRun, ActiveRunStatus } from "../types";
import type { ChatMessage } from "../../../types/dto";
import { RunSchema } from "../../../types/dto";
import { useMemo } from "react";

type UseRunLifecycleParams = {
  chatId: string | undefined;
  chatTitle: string | undefined;
  messages: ChatMessage[];
  latestRunId: string | null;
  selectedModel: string;
  customModel: string;
  hydrateReportFromArtifacts: (runId: string, targetChatId?: string | null) => Promise<void>;
  setCompletedRunArtifacts: React.Dispatch<React.SetStateAction<Record<string, import("../../../types/dto").Artifact[]>>>;
};

export function useRunLifecycle({
  chatId,
  chatTitle,
  messages,
  latestRunId,
  selectedModel,
  customModel,
  hydrateReportFromArtifacts,
  setCompletedRunArtifacts,
}: UseRunLifecycleParams) {
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null);
  const [progressDetailsOpen, setProgressDetailsOpen] = useState(false);

  const lastEventIdRef = useRef<number>(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const runStatusCheckRef = useRef<number>(0);
  const runHydrationRef = useRef<{ chatId: string | null; runId: string | null }>({
    chatId: null,
    runId: null,
  });

  const cancelRun = useCancelRunMutation(activeRun?.runId ?? "");
  const retryRun = useRetryRunMutation(activeRun?.runId ?? "");

  // Reset transient run state when chatId changes
  useEffect(() => {
    runHydrationRef.current = { chatId: null, runId: null };
    runStatusCheckRef.current = 0;
    lastEventIdRef.current = 0;
    setActiveRun(null);
    setProgressDetailsOpen(false);
  }, [chatId]);

  const sseEnabled = Boolean(activeRun?.runId && activeRun.status === "running");
  const sse = useSSE(
    activeRun?.runId ? `/runs/${encodeURIComponent(activeRun.runId)}/events` : null,
    sseEnabled,
  );

  const progressCard = useMemo(
    () =>
      activeRun
        ? buildResearchProgressCardModel({
            activeRun,
            chatTitle,
            messages,
            events: sse.events,
          })
        : null,
    [activeRun, chatTitle, messages, sse.events],
  );

  // Reset progress details panel when run changes
  useEffect(() => {
    setProgressDetailsOpen(false);
  }, [activeRun?.runId]);

  async function handleRunCompletion(
    runId: string,
    status: ActiveRunStatus,
    targetChatId: string | null = chatId ?? null,
  ) {
    if (status === "canceled") {
      let cleared = false;
      setActiveRun((prev) => {
        if (!prev || prev.runId !== runId) return prev;
        cleared = true;
        return null;
      });
      if (cleared) lastEventIdRef.current = 0;
      return;
    }

    if (status === "succeeded") {
      await hydrateReportFromArtifacts(runId, targetChatId);
    }

    let cleared = false;
    setActiveRun((prev) => {
      if (!prev || prev.runId !== runId) return prev;
      cleared = true;
      return null;
    });
    if (cleared) lastEventIdRef.current = 0;
  }

  async function hydrateRunFailure(runId: string, fallbackError?: string) {
    const run = await apiFetchJson(`/runs/${encodeURIComponent(runId)}`, {
      schema: RunSchema,
    }).catch(() => null);

    if (!run) {
      if (fallbackError) {
        setActiveRun((prev) =>
          prev
            ? {
                ...prev,
                status: "failed",
                primaryText: "Resuming report generation...",
                secondaryText: fallbackError,
                error: fallbackError,
              }
            : prev,
        );
      }
      return;
    }

    if (run.status === "failed") {
      const message = run.error_message ?? fallbackError ?? "The run failed.";
      setActiveRun((prev) =>
        prev
          ? {
              ...prev,
              status: "failed",
              primaryText: "Something went wrong",
              secondaryText: message,
              error: message,
            }
          : prev,
      );
      return;
    }

    if (run.status === "succeeded" || run.status === "canceled") {
      void handleRunCompletion(runId, run.status as ActiveRunStatus);
      return;
    }

    if (fallbackError) {
      setActiveRun((prev) =>
        prev ? { ...prev, secondaryText: fallbackError } : prev,
      );
    }
  }

  // Handle SSE events
  useEffect(() => {
    if (!activeRun) return;
    if (sse.events.length === 0) return;

    const fresh = sse.events.filter((evt) => {
      const idValue = (evt as { id?: number }).id ?? 0;
      if (idValue <= lastEventIdRef.current) return false;
      lastEventIdRef.current = Math.max(lastEventIdRef.current, idValue);
      return true;
    });

    if (fresh.length === 0) return;

    let terminal: ActiveRunStatus | null = null;
    let terminalError: string | undefined;
    let nextPrimary: string | undefined;
    let nextSecondary: string | undefined;

    for (const evt of fresh) {
      const { status, primaryText, secondaryText } = deriveRunUpdate(evt);

      if (status && ["succeeded", "failed", "canceled"].includes(status)) {
        terminal = status as ActiveRunStatus;
        if (status === "failed") {
          terminalError = typeof evt.message === "string" ? evt.message : undefined;
        }
      } else {
        nextPrimary = primaryText;
        nextSecondary = secondaryText;
      }
    }

    if (terminal) {
      if (terminal === "failed") {
        void hydrateRunFailure(activeRun.runId, terminalError);
      } else {
        void handleRunCompletion(activeRun.runId, terminal);
      }
      return;
    }

    if (!nextPrimary) return;

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setActiveRun((prev) =>
        prev
          ? {
              ...prev,
              primaryText: nextPrimary ?? prev.primaryText,
              secondaryText: nextSecondary ?? prev.secondaryText,
              status: "running",
            }
          : prev,
      );
    }, 120);
  }, [activeRun, sse.events]);

  // Clean up debounce on unmount
  useEffect(
    () => () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    },
    [],
  );

  // Handle SSE error/close → poll run status
  useEffect(() => {
    if (!activeRun || activeRun.status !== "running") return;
    if (sse.state !== "error" && sse.state !== "closed") return;

    const now = Date.now();
    if (now - runStatusCheckRef.current < 2000) return;
    runStatusCheckRef.current = now;

    void hydrateRunFailure(activeRun.runId, sse.lastError ?? undefined);
  }, [activeRun, sse.state, sse.lastError]);

  // Hydrate run on initial load (when messages contain a run_id)
  useEffect(() => {
    if (!chatId) return;
    if (!latestRunId) return;
    if (activeRun) return;

    if (
      runHydrationRef.current.chatId === chatId &&
      runHydrationRef.current.runId === latestRunId
    )
      return;
    runHydrationRef.current = { chatId, runId: latestRunId };

    void (async () => {
      const run = await apiFetchJson(`/runs/${encodeURIComponent(latestRunId)}`, {
        schema: RunSchema,
      }).catch(() => null);

      if (!run) return;

      if (run.status === "succeeded") {
        // Skip rehydration if the user explicitly cleared this run's report.
        if (chatId && getClearedRunId(chatId) === latestRunId) return;
        await hydrateReportFromArtifacts(latestRunId, chatId);
        return;
      }

      if (run.status === "failed") {
        const message = run.error_message ?? "The run failed.";
        setActiveRun({
          runId: latestRunId,
          status: "failed",
          question: typeof run.question === "string" ? run.question : undefined,
          primaryText: "Something went wrong",
          secondaryText: message,
          startedAt: run.created_at ?? new Date().toISOString(),
          error: message,
        });
        return;
      }

      if (run.status === "blocked") {
        const message =
          run.error_message ??
          "Another research run is already in progress. Retry after it finishes.";
        setActiveRun({
          runId: latestRunId,
          status: "blocked",
          question: typeof run.question === "string" ? run.question : undefined,
          primaryText: "Run blocked",
          secondaryText: message,
          startedAt: run.created_at ?? new Date().toISOString(),
          error: message,
        });
        return;
      }

      if (run.status === "canceled") return;

      setActiveRun({
        runId: latestRunId,
        status: "running",
        question: typeof run.question === "string" ? run.question : undefined,
        primaryText: "Resuming report generation\u2026",
        secondaryText: "Checking progress...",
        startedAt: run.created_at ?? new Date().toISOString(),
      });
      lastEventIdRef.current = 0;
    })();
  }, [activeRun, chatId, hydrateReportFromArtifacts, latestRunId]);

  async function onCancelRun() {
    if (!activeRun) return;
    try {
      await cancelRun.mutateAsync();
      setActiveRun((prev) => (prev ? { ...prev, primaryText: "Stopping run..." } : prev));
    } catch {
      setActiveRun(null);
    }
  }

  async function onRetryRun() {
    if (!activeRun) return;
    try {
      const modelValue =
        selectedModel === CUSTOM_MODEL_VALUE ? customModel.trim() : selectedModel.trim();
      const run = await retryRun.mutateAsync(modelValue || undefined);
      const blockedMessage =
        run.error_message ??
        "Another research run is already in progress. Retry after it finishes.";

      setActiveRun((prev) => {
        if (!prev) return prev;
        if (run.status === "blocked") {
          return {
            ...prev,
            status: "blocked",
            primaryText: "Run blocked",
            secondaryText: blockedMessage,
            error: blockedMessage,
          };
        }
        return {
          ...prev,
          status: "running",
          primaryText: "Retrying run",
          secondaryText: undefined,
          error: undefined,
        };
      });
    } catch {
      // Leave the current run state unchanged if retry fails.
    }
  }

  const reportStatusLabel = activeRun
    ? activeRun.status === "blocked"
      ? "BLOCKED"
      : activeRun.status === "failed"
        ? "FAILED"
        : activeRun.status === "canceled"
          ? "CANCELED"
          : activeRun.status === "succeeded"
            ? "READY"
            : "PROCESSING"
    : "READY";

  const reportStatusClasses = activeRun
    ? activeRun.status === "blocked"
      ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
      : activeRun.status === "failed"
        ? "border-rose-500/30 bg-rose-500/10 text-rose-300"
        : activeRun.status === "canceled"
          ? "border-slate-600 bg-slate-800 text-slate-300"
          : "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
    : "border-emerald-500/30 bg-emerald-500/10 text-emerald-400";

  return {
    activeRun,
    setActiveRun,
    lastEventIdRef,
    progressCard,
    progressDetailsOpen,
    setProgressDetailsOpen,
    reportStatusLabel,
    reportStatusClasses,
    onCancelRun,
    onRetryRun,
  };
}
