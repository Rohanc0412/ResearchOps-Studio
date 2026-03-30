import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Download } from "lucide-react";
import {
  flattenInfiniteMessages,
  useChatConversationsQuery,
  useChatMessagesInfiniteQuery,
  useSendChatMessageMutationInfinite
} from "../api/chat";
import { apiFetchJson } from "../api/client";
import { useProjectQuery } from "../api/projects";
import { useCancelRunMutation, useRetryRunMutation } from "../api/runs";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";
import { ChatComposer } from "../features/chat/components/ChatComposer";
import { ChatMessageList } from "../features/chat/components/ChatMessageList";
import { MODEL_OPTIONS, CUSTOM_MODEL_VALUE, DEFAULT_HOSTED_MODEL, EMPTY_REPORT } from "../features/chat/constants";
import { ConfigureRunModal, type StageModels } from "../features/chat/components/ConfigureRunModal";
import { ExportModal } from "../features/chat/components/ExportModal";
import { ReportPane } from "../features/chat/components/ReportPane";
import { ShareModal } from "../features/chat/components/ShareModal";
import { generateClientMessageId } from "../features/chat/lib/ids";
import { buildFinalResponse, extractAllRunIds, extractLatestRunId } from "../features/chat/lib/reportArtifacts";
import { extractReportTitle, parseMarkdownToSections } from "../features/chat/lib/reportParser";
import { loadStoredReport, persistReport } from "../features/chat/lib/reportStorage";
import { deriveRunUpdate } from "../features/chat/lib/runUpdates";
import type { ActiveRun, ActiveRunStatus, Report } from "../features/chat/types";
import { useSSE } from "../hooks/useSSE";
import { buildResearchProgressCardModel } from "../components/run/researchProgress";
import { ArtifactSchema, RunSchema, type Artifact, type Run } from "../types/dto";
import { z } from "zod";

const ArtifactsSchema = z.array(ArtifactSchema);

export function ChatViewPage() {
  const { projectId, chatId } = useParams();

  const location = useLocation();

  const navigate = useNavigate();

  const id = projectId ?? "";

  const project = useProjectQuery(id);

  const conversations = useChatConversationsQuery(id, 200);

  const messagesQuery = useChatMessagesInfiniteQuery(chatId ?? "", 200);

  const sendChat = useSendChatMessageMutationInfinite(chatId ?? "", 200, {
    onStatus: () => setWebSearching(true),
  });

  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null);

  const cancelRun = useCancelRunMutation(activeRun?.runId ?? "");
  const retryRun = useRetryRunMutation(activeRun?.runId ?? "");

  const [draft, setDraft] = useState("");

  const [isTyping, setIsTyping] = useState(false);

  const [webSearching, setWebSearching] = useState(false);

  const [selectedModel, setSelectedModel] = useState(DEFAULT_HOSTED_MODEL);
  const [customModel, setCustomModel] = useState("");
  const [showRunModal, setShowRunModal] = useState(false);
  const [pendingDraft, setPendingDraft] = useState<string | null>(null);

  // Initialised from navigation state so "Run research report" on project page carries through.
  const [runPipelineArmed, setRunPipelineArmed] = useState(() => {
    if (!location.state || typeof location.state !== "object") return false;
    const state = location.state as { runPipeline?: boolean };
    return state.runPipeline === true;
  });

  const [report, setReport] = useState<Report>(EMPTY_REPORT);
  const [completedRunArtifacts, setCompletedRunArtifacts] = useState<Record<string, Artifact[]>>({});

  const reportChatIdRef = useRef<string | null>(null);

  const [highlightedSection, setHighlightedSection] = useState<string | null>(null);

  const [showExportModal, setShowExportModal] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);

  const [exportNotification, setExportNotification] = useState<string | null>(null);
  const [progressDetailsOpen, setProgressDetailsOpen] = useState(false);

  const lastEventIdRef = useRef<number>(0);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const highlightTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const runStatusCheckRef = useRef<number>(0);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const reportContentRef = useRef<HTMLDivElement>(null);

  const initialMessage = useMemo(() => {
    if (!location.state || typeof location.state !== "object") return null;

    const state = location.state as { initialMessage?: string };

    return state.initialMessage ?? null;
  }, [location.state]);

  const initialMessageSentRef = useRef(false);

  const chat = useMemo(() => {
    const items = conversations.data?.items ?? [];
    return items.find((item) => item.id === chatId) ?? null;
  }, [conversations.data, chatId]);

  const messages = flattenInfiniteMessages(messagesQuery.data);
  const latestRunId = useMemo(() => extractLatestRunId(messages), [messages]);
  const allRunIds = useMemo(() => extractAllRunIds(messages), [messages]);
  const runHydrationRef = useRef<{ chatId: string | null; runId: string | null }>({
    chatId: null,
    runId: null
  });
  const hydratedRunArtifactsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!chatId) {
      reportChatIdRef.current = null;
      runHydrationRef.current = { chatId: null, runId: null };
      runStatusCheckRef.current = 0;
      lastEventIdRef.current = 0;
      setActiveRun(null);
      setReport(EMPTY_REPORT);
      setCompletedRunArtifacts({});
      hydratedRunArtifactsRef.current = new Set();
      return;
    }

    const stored = loadStoredReport(chatId);
    reportChatIdRef.current = chatId;
    runHydrationRef.current = { chatId: null, runId: null };
    runStatusCheckRef.current = 0;
    lastEventIdRef.current = 0;
    setActiveRun(null);
    setReport(stored ?? EMPTY_REPORT);
    setCompletedRunArtifacts({});
    hydratedRunArtifactsRef.current = new Set();
  }, [chatId]);

  useEffect(() => {
    if (!chatId) return;
    if (reportChatIdRef.current !== chatId) return;
    persistReport(chatId, report);
  }, [chatId, report]);

  useEffect(() => {
    if (!initialMessage || !chatId || initialMessageSentRef.current) return;

    initialMessageSentRef.current = true;

    navigate(location.pathname, { replace: true, state: {} });

    // instead of auto-sending, so the user can configure per-stage models.
    if (runPipelineArmed) {
      setPendingDraft(initialMessage);
      setShowRunModal(true);
      return;
    }

    void sendMessage(initialMessage).catch(() => {});
  }, [initialMessage, chatId, location.pathname, navigate, runPipelineArmed]);

  // Scroll to bottom when messages change
  useEffect(() => {
    const node = messagesEndRef.current;
    if (node && typeof node.scrollIntoView === "function") {
      node.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages.length]);

  const sseEnabled = Boolean(activeRun?.runId && activeRun.status === "running");
  const sse = useSSE(
    activeRun?.runId ? `/runs/${encodeURIComponent(activeRun.runId)}/events` : null,
    sseEnabled
  );
  const progressCard = useMemo(
    () =>
      activeRun
        ? buildResearchProgressCardModel({
            activeRun,
            chatTitle: chat?.title,
            messages,
            events: sse.events
          })
        : null,
    [activeRun, chat?.title, messages, sse.events]
  );
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

  useEffect(() => {
    setProgressDetailsOpen(false);
  }, [activeRun?.runId]);

  useEffect(() => {
    if (!activeRun?.runId) return;
    reportContentRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [activeRun?.runId]);

  useEffect(() => {
    if (!chatId) return;

    const toFetch = allRunIds.filter(
      (runId) =>
        runId !== activeRun?.runId &&
        !hydratedRunArtifactsRef.current.has(runId)
    );
    if (toFetch.length === 0) return;

    for (const runId of toFetch) {
      hydratedRunArtifactsRef.current.add(runId);
      void apiFetchJson(`/runs/${encodeURIComponent(runId)}/artifacts`, { schema: ArtifactsSchema })
        .then((artifacts) => {
          if (artifacts && artifacts.length > 0) {
            setCompletedRunArtifacts((prev) => ({ ...prev, [runId]: artifacts }));
          }
        })
        .catch(() => {});
    }
  }, [chatId, allRunIds, activeRun?.runId]);

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
              status: "running"
            }
          : prev
      );
    }, 120);
  }, [activeRun, sse.events]);

  useEffect(
    () => () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    },
    []
  );

  useEffect(() => {
    if (!activeRun || activeRun.status !== "running") return;
    if (sse.state !== "error" && sse.state !== "closed") return;

    const now = Date.now();
    if (now - runStatusCheckRef.current < 2000) return;
    runStatusCheckRef.current = now;

    void hydrateRunFailure(activeRun.runId, sse.lastError ?? undefined);
  }, [activeRun, sse.state, sse.lastError]);

  const hydrateReportFromArtifacts = useCallback(
    async (runId: string, targetChatId: string | null = chatId ?? null) => {
      const artifacts = await apiFetchJson(`/runs/${encodeURIComponent(runId)}/artifacts`, {
        schema: ArtifactsSchema
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
        sections: parsedSections
      }));

      const firstSection = parsedSections[0];
      if (firstSection) {
        setHighlightedSection(firstSection.id);
        if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current);
        highlightTimeoutRef.current = setTimeout(() => setHighlightedSection(null), 2000);
      }
    },
    [chatId, setHighlightedSection, setReport, setCompletedRunArtifacts]
  );

  // Clean up highlight timeout on unmount to prevent state updates on unmounted component.
  useEffect(() => {
    return () => {
      if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current);
    };
  }, []);

  async function handleRunCompletion(
    runId: string,
    status: ActiveRunStatus,
    targetChatId: string | null = chatId ?? null
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
      schema: RunSchema
    }).catch(() => null as Run | null);

    if (!run) {
      if (fallbackError) {
        setActiveRun((prev) =>
          prev
            ? {
                ...prev,
                status: "failed",
                primaryText: "Resuming report generation...",
                secondaryText: fallbackError,
                error: fallbackError
              }
            : prev
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
              error: message
            }
          : prev
      );
      return;
    }

    if (run.status === "succeeded" || run.status === "canceled") {
      void handleRunCompletion(runId, run.status as ActiveRunStatus);
      return;
    }

    if (fallbackError) {
      setActiveRun((prev) =>
        prev
          ? {
              ...prev,
              secondaryText: fallbackError
            }
          : prev
      );
    }
  }

  useEffect(() => {
    if (!chatId) return;
    if (!latestRunId) return;
    if (activeRun) return;

    if (runHydrationRef.current.chatId === chatId && runHydrationRef.current.runId === latestRunId) return;
    runHydrationRef.current = { chatId, runId: latestRunId };

    void (async () => {
      const run = await apiFetchJson(`/runs/${encodeURIComponent(latestRunId)}`, {
        schema: RunSchema
      }).catch(() => null as Run | null);

      if (!run) return;

      if (run.status === "succeeded") {
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
          error: message
        });
        return;
      }

      if (run.status === "blocked") {
        const message = run.error_message ?? "Another research run is already in progress. Retry after it finishes.";
        setActiveRun({
          runId: latestRunId,
          status: "blocked",
          question: typeof run.question === "string" ? run.question : undefined,
          primaryText: "Run blocked",
          secondaryText: message,
          startedAt: run.created_at ?? new Date().toISOString(),
          error: message
        });
        return;
      }

      if (run.status === "canceled") return;

      // queued/created/running => resume progress banner + SSE
      setActiveRun({
        runId: latestRunId,
        status: "running",
        question: typeof run.question === "string" ? run.question : undefined,
        primaryText: "Resuming report generationâ€¦",
        secondaryText: "Checking progress...",
        startedAt: run.created_at ?? new Date().toISOString()
      });
      lastEventIdRef.current = 0;
    })();
  }, [activeRun, chatId, hydrateReportFromArtifacts, latestRunId]);

  async function sendMessage(text: string, stageModels?: StageModels) {
    const trimmed = text.trim();
    if (!trimmed || !chatId) return;
    const isAction = trimmed.startsWith("__ACTION__:");
    const modelValue =
      selectedModel === CUSTOM_MODEL_VALUE ? customModel.trim() : selectedModel.trim();

    setIsTyping(true);

    try {
      const response = await sendChat.mutateAsync({
        conversation_id: chatId,
        project_id: id || undefined,
        message: trimmed,

        client_message_id: generateClientMessageId(),

        llm_provider: "hosted",
        llm_model: modelValue ? modelValue : undefined,
        force_pipeline: runPipelineArmed && !isAction,
        stage_models: stageModels ?? undefined,
      });

      const assistant = response.assistant_message;

      if (assistant?.type === "run_started") {
        const runId = assistant.content_json?.["run_id"];
        const runQuestion = assistant.content_json?.["question"];
        const runStatus = assistant.content_json?.["status"];
        const blockedMessage =
          typeof assistant.content_text === "string" && assistant.content_text.trim()
            ? assistant.content_text
            : "Another research run is already in progress. Retry after it finishes.";
        if (typeof runId === "string") {
          setActiveRun({
            runId,
            status: runStatus === "blocked" ? "blocked" : "running",
            question: typeof runQuestion === "string" ? runQuestion : undefined,
            primaryText: runStatus === "blocked" ? "Run blocked" : "Starting run...",
            secondaryText: runStatus === "blocked" ? blockedMessage : undefined,
            startedAt: new Date().toISOString(),
            error: runStatus === "blocked" ? blockedMessage : undefined
          });

          lastEventIdRef.current = runStatus === "blocked" ? lastEventIdRef.current : 0;
        }
      }

    } finally {
      setIsTyping(false);
      setWebSearching(false);
    }
  }

  async function onSend() {
    const text = draft.trim();
    if (!text) return;

    if (runPipelineArmed) {
      setPendingDraft(text);
      setShowRunModal(true);
      return;
    }

    try {
      await sendMessage(text);

      setDraft("");
      setRunPipelineArmed(false);
    } catch {
      // Preserve the current draft so the user can retry.
    }
  }

  async function handleStartRun(stageModels: StageModels) {
    setShowRunModal(false);
    if (!pendingDraft) return;
    const text = pendingDraft;
    setPendingDraft(null);
    try {
      await sendMessage(text, stageModels);
      setDraft("");
      setRunPipelineArmed(false);
    } catch {
      // Keep draft for retry.
    }
  }

  async function onAnswerNow() {
    if (!activeRun) return;

    try {
      await cancelRun.mutateAsync();

      setActiveRun((prev) => (prev ? { ...prev, primaryText: "Stopping run..." } : prev));
    } catch {
      setActiveRun(null);
    }
  }

  async function onRetry() {
    if (!activeRun) return;

    try {
      const modelValue =
        selectedModel === CUSTOM_MODEL_VALUE ? customModel.trim() : selectedModel.trim();
      const run = await retryRun.mutateAsync(modelValue || undefined);
      const blockedMessage =
        run.error_message ?? "Another research run is already in progress. Retry after it finishes.";

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

  function handleSectionEdit(sectionId: string, newContent: string) {
    setReport((prev) => ({
      ...prev,
      sections: prev.sections.map((s) => (s.id === sectionId ? { ...s, content: [{ text: newContent }] } : s))
    }));
  }

  function handleClear() {
    if (window.confirm("Are you sure you want to clear the report?")) {
      setReport(EMPTY_REPORT);
      if (chatId) {
        persistReport(chatId, EMPTY_REPORT);
      }
    }
  }

  async function handleExport(format: string) {
    setShowExportModal(false);
    setExportNotification(`Exporting as ${format.toUpperCase()}...`);

    try {
      const { exportReport } = await import("../features/chat/lib/reportExport");
      await exportReport(report, format);
      setExportNotification(`Report downloaded as ${format.toUpperCase()}`);
      setTimeout(() => setExportNotification(null), 2000);
    } catch (error) {
      setExportNotification(`Export failed: ${error instanceof Error ? error.message : "Unknown error"}`);
      setTimeout(() => setExportNotification(null), 3000);
    }
  }

  if (project.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="Loading..." />
      </div>
    );
  }

  if (project.isError) {
    return <ErrorBanner message={project.error instanceof Error ? project.error.message : "Failed to load project"} />;
  }

  const p = project.data;
  if (!p) return null;

  if (conversations.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="Loading conversation..." />
      </div>
    );
  }

  if (!chat) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-slate-400">Chat not found</div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 bg-slate-950 text-slate-200">
      {/* Left Panel - Chat */}
      <div className="flex w-[45%] min-h-0 flex-col border-r border-slate-800">
        {/* Chat Header */}
        <div className="border-b border-slate-800 px-6 py-5">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => navigate(`/projects/${id}`)}
              className="flex h-8 w-8 items-center justify-center rounded-md text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <div>
              <h1 className="font-mono text-xl font-semibold text-slate-100">{chat.title}</h1>
              <p className="mt-1 text-sm text-slate-500">{p.name}</p>
            </div>
          </div>
        </div>

                <ChatMessageList
          messages={messages}
          isTyping={isTyping}
          webSearching={webSearching}
          isActionPending={isTyping}
          activeRunId={activeRun?.runId}
          completedRunArtifacts={completedRunArtifacts}
          messagesEndRef={messagesEndRef}
          onAction={(actionId) => {
            void sendMessage(`__ACTION__:${actionId}`);
          }}
        />

        <ChatComposer
          draft={draft}
          isTyping={isTyping}
          runPipelineArmed={runPipelineArmed}
          selectedModel={selectedModel}
          customModel={customModel}
          modelOptions={MODEL_OPTIONS}
          customModelValue={CUSTOM_MODEL_VALUE}
          onDraftChange={setDraft}
          onSend={() => {
            void onSend();
          }}
          onQuickAction={(action) => {
            setDraft(action);
            setRunPipelineArmed(false);
          }}
          onTogglePipeline={() => setRunPipelineArmed((prev) => !prev)}
          onSelectedModelChange={setSelectedModel}
          onCustomModelChange={setCustomModel}
        />
      </div>

      <ReportPane
        report={report}
        activeRun={activeRun}
        progressCard={progressCard}
        progressDetailsOpen={progressDetailsOpen}
        reportStatusLabel={reportStatusLabel}
        reportStatusClasses={reportStatusClasses}
        highlightedSection={highlightedSection}
        contentRef={reportContentRef}
        onToggleExpanded={() => setProgressDetailsOpen((prev) => !prev)}
        onCancel={activeRun?.status === 'running' ? () => void onAnswerNow() : undefined}
        onRetry={
          activeRun && (activeRun.status === 'failed' || activeRun.status === 'blocked')
            ? () => void onRetry()
            : undefined
        }
        onExport={() => setShowExportModal(true)}
        onClear={handleClear}
        onShare={() => setShowShareModal(true)}
        onSectionEdit={handleSectionEdit}
      />
      {/* Modals */}
      <ExportModal isOpen={showExportModal} onClose={() => setShowExportModal(false)} onExport={handleExport} />
      <ShareModal isOpen={showShareModal} onClose={() => setShowShareModal(false)} />
      <ConfigureRunModal
        open={showRunModal}
        onCancel={() => { setShowRunModal(false); setPendingDraft(null); }}
        onStart={handleStartRun}
      />

      {/* Export Notification */}
      {exportNotification && (
        <div className="fixed bottom-6 right-6 flex items-center gap-2.5 rounded-xl border border-emerald-500/30 bg-slate-900 px-5 py-3.5 text-sm font-medium text-emerald-400 shadow-xl">
          <Download className="h-4 w-4" />
          {exportNotification}
        </div>
      )}
    </div>
  );
}




