import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Download, Send, Share2, Sparkles, Trash2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  flattenInfiniteMessages,
  useChatConversationsQuery,
  useChatMessagesInfiniteQuery,
  useSendChatMessageMutationInfinite
} from "../api/chat";
import { apiFetchJson } from "../api/client";
import { useProjectQuery } from "../api/projects";
import { useCancelRunMutation, useRetryRunMutation } from "../api/runs";
import { ResearchProgressCard } from "../components/run/ResearchProgressCard";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";
import { MODEL_OPTIONS, CUSTOM_MODEL_VALUE, DEFAULT_HOSTED_MODEL, EMPTY_REPORT } from "../features/chat/constants";
import { ConfigureRunModal, type StageModels } from "../features/chat/components/ConfigureRunModal";
import { ExportModal } from "../features/chat/components/ExportModal";
import { ReportSectionView } from "../features/chat/components/ReportSectionView";
import { ShareModal } from "../features/chat/components/ShareModal";
import { RunArtifactLinks } from "../features/chat/components/RunArtifactLinks";
import { TypingIndicator } from "../features/chat/components/TypingIndicator";
import { generateClientMessageId } from "../features/chat/lib/ids";
import {
  chatMarkdownComponents,
  displayMessageText,
  formatActionLabel,
  normalizeChatMarkdown
} from "../features/chat/lib/messageFormatting";
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

  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const reportContentRef = useRef<HTMLDivElement | null>(null);

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
      setReport(EMPTY_REPORT);
      setCompletedRunArtifacts({});
      hydratedRunArtifactsRef.current = new Set();
      return;
    }

    const stored = loadStoredReport(chatId);
    reportChatIdRef.current = chatId;
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
    ? activeRun.status === "failed"
      ? "FAILED"
      : activeRun.status === "canceled"
        ? "CANCELED"
        : activeRun.status === "succeeded"
          ? "READY"
          : "PROCESSING"
    : "READY";
  const reportStatusClasses = activeRun
    ? activeRun.status === "failed"
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
        void handleRunCompletion(terminal);
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
    async (runId: string) => {
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
    [setHighlightedSection, setReport, setCompletedRunArtifacts]
  );

  // Clean up highlight timeout on unmount to prevent state updates on unmounted component.
  useEffect(() => {
    return () => {
      if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current);
    };
  }, []);

  async function handleRunCompletion(status: ActiveRunStatus) {
    if (!activeRun) return;

    const runId = activeRun.runId;

    if (status === "canceled") {
      setActiveRun(null);
      lastEventIdRef.current = 0;
      return;
    }

    if (status === "succeeded") {
      await hydrateReportFromArtifacts(runId);
    }

    setActiveRun(null);
    lastEventIdRef.current = 0;
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
                primaryText: "Something went wrong",
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
      void handleRunCompletion(run.status as ActiveRunStatus);
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
        await hydrateReportFromArtifacts(latestRunId);
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

      if (run.status === "canceled") return;

      // queued/created/running/blocked => resume progress banner + SSE
      setActiveRun({
        runId: latestRunId,
        status: "running",
        question: typeof run.question === "string" ? run.question : undefined,
        primaryText: "Resuming report generation…",
        secondaryText: "Checking progress…",
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
        if (typeof runId === "string") {
          setActiveRun({
            runId,
            status: "running",
            question: typeof runQuestion === "string" ? runQuestion : undefined,
            primaryText: "Starting run...",
            startedAt: new Date().toISOString()
          });

          lastEventIdRef.current = 0;
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
      await retryRun.mutateAsync(modelValue || undefined);

      setActiveRun((prev) =>
        prev ? { ...prev, status: "running", primaryText: "Retrying run", secondaryText: undefined } : prev
      );
    } catch {
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

  const quickActions = ["Add conclusion", "Add recommendations", "Summarize findings", "Add references"];
  const reportActionButtonClasses =
    "inline-flex h-11 shrink-0 items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-4 text-sm font-medium text-slate-200 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:text-slate-600";

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

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-6">
          {messages.map((message) => {
            const isUser = message.role === "user";
            const isOffer = message.type === "pipeline_offer";
            const isRunStarted = message.type === "run_started";
            const isError = message.type === "error";

            const runId = isRunStarted ? (message.content_json?.["run_id"] as string | undefined) : undefined;

            const offer = message.content_json?.["offer"];

            const actions = Array.isArray((offer as { actions?: unknown[] } | undefined)?.actions)
              ? ((offer as { actions: Array<{ id?: string; label?: string }> }).actions ?? [])
              : [];

            return (
              <div key={message.id} className={`mb-4 flex flex-col ${isUser ? "items-end" : "items-start"}`}>
                <div
                  // assistant markdown uses normal whitespace so blank lines don't compound with markdown block spacing.
                  className={`max-w-[90%] ${
                    isUser || isError || message.type === "action" ? "whitespace-pre-wrap" : "whitespace-normal"
                  } rounded-2xl px-4 py-3.5 text-sm leading-relaxed ${
                    isUser
                      ? "rounded-br-sm border border-emerald-500/30 bg-emerald-500/15 text-slate-200"
                      : isError
                        ? "rounded-bl-sm border border-rose-500/40 bg-rose-500/10 text-rose-100"
                        : "rounded-bl-sm border border-slate-800 bg-slate-900 text-slate-200"
                  }`}
                >
                  {message.type === "action" ? (
                    <span>{displayMessageText(message)}</span>
                  ) : (
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>
                      {normalizeChatMarkdown(message.content_text)}
                    </ReactMarkdown>
                  )}

                  {isRunStarted && runId ? (
                    (() => {
                      const runArtifacts = completedRunArtifacts[runId];
                      if (runArtifacts && runArtifacts.length > 0) {
                        return <RunArtifactLinks runId={runId} artifacts={runArtifacts} />;
                      }
                      if (activeRun?.runId === runId) {
                        return (
                          <div className="mt-2 text-xs text-slate-400">
                            Tracking progress in the research report panel.
                          </div>
                        );
                      }
                      return null;
                    })()
                  ) : null}
                </div>

                {isOffer && actions.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {actions.map((action) => (
                      <button
                        key={action.id ?? action.label}
                        onClick={() => {
                          if (!action.id) return;

                          void sendMessage(`__ACTION__:${action.id}`);
                        }}
                        disabled={isTyping}
                        className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-200 transition-colors hover:border-emerald-500/60 hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {action.label ?? formatActionLabel(action.id ?? null)}
                      </button>
                    ))}
                  </div>
                ) : null}

                <div className="mt-1.5 font-mono text-xs text-slate-500">
                  {new Date(message.created_at).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                    hour12: false
                  })}
                </div>
              </div>
            );
          })}

          {isTyping && (
            <div className="inline-block rounded-2xl rounded-bl-sm border border-slate-800 bg-slate-900 px-4 py-3.5">
              {webSearching ? (
                <span className="animate-breathe text-sm text-slate-400">
                  Searching the web...
                </span>
              ) : (
                <TypingIndicator />
              )}
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Quick Actions */}
        <div className="flex flex-wrap gap-2 px-6 pb-3">
          {quickActions.map((action) => (
            <button
              key={action}
              onClick={() => { setDraft(action); setRunPipelineArmed(false); }}
              className="rounded-full border border-slate-700 bg-slate-900 px-3.5 py-2 text-xs text-slate-400 transition-colors hover:border-emerald-500/30 hover:bg-emerald-500/10 hover:text-emerald-400"
            >
              {action}
            </button>
          ))}
        </div>

        {/* Input */}
        <div className="border-t border-slate-800 px-6 py-4">
          <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-slate-400">
            <span>LLM model</span>
            <div className="flex flex-1 flex-wrap items-center gap-2">
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="min-w-[220px] rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-emerald-500/50 focus:outline-none"
              >
                {MODEL_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              {selectedModel === CUSTOM_MODEL_VALUE ? (
                <input
                  value={customModel}
                  onChange={(e) => setCustomModel(e.target.value)}
                  placeholder="Enter model id"
                  className="min-w-[220px] flex-1 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-emerald-500/50 focus:outline-none"
                />
              ) : null}
            </div>
            <button
              type="button"
              data-testid="pipeline-toggle"
              aria-pressed={runPipelineArmed}
              onClick={() => setRunPipelineArmed((prev) => !prev)}
              className={`rounded-full border px-3.5 py-2 text-xs transition-colors ${
                runPipelineArmed
                  ? "border-emerald-500/60 bg-emerald-500/20 text-emerald-200"
                  : "border-slate-700 bg-slate-900 text-slate-400 hover:border-emerald-500/30 hover:text-emerald-300"
              }`}
            >
              Run research report
            </button>
          </div>

          <div className="flex items-end gap-3">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void onSend();
                }
              }}
              placeholder={runPipelineArmed ? "Describe your research topic — report will run on send…" : "Ask a question or request a report..."}
              rows={1}
              className="flex-1 resize-none rounded-xl border border-slate-700 bg-slate-900 px-4 py-3.5 text-sm text-slate-200 outline-none transition-colors focus:border-emerald-500/50"
            />
            <button
              onClick={() => void onSend()}
              disabled={!draft.trim() || isTyping}
              className={`flex h-12 w-12 items-center justify-center rounded-xl transition-colors ${
                draft.trim() && !isTyping
                  ? "bg-emerald-500 text-slate-900 hover:bg-emerald-400"
                  : "cursor-not-allowed bg-emerald-500/30 text-slate-500"
              }`}
            >
              <Send className="h-5 w-5" />
            </button>
          </div>
        </div>
      </div>

      {/* Right Panel - Report */}
      <div className="flex w-[55%] min-h-0 flex-col bg-slate-950">
        {/* Report Header */}
        <div className="flex items-center justify-between border-b border-slate-800 px-8 py-5">
          <h2 className="font-mono text-lg font-semibold tracking-tight text-slate-100 md:text-xl">{report.title}</h2>
          <div className="flex items-center gap-3">
            <div
              className={`inline-flex h-9 shrink-0 items-center gap-2 rounded-full border px-3.5 text-[0.7rem] font-medium uppercase tracking-[0.16em] ${reportStatusClasses}`}
            >
              <div
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                  activeRun?.status === "failed"
                    ? "bg-rose-400"
                    : activeRun?.status === "canceled"
                      ? "bg-slate-400"
                      : "animate-pulse bg-emerald-500"
                }`}
              />
              {reportStatusLabel}
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap gap-3 border-b border-slate-800 px-8 py-4">
          <button
            onClick={() => setShowExportModal(true)}
            disabled={report.sections.length === 0}
            className={reportActionButtonClasses}
          >
            <Download className="h-4 w-4" />
            Export
          </button>
          <button
            onClick={handleClear}
            disabled={report.sections.length === 0}
            className={reportActionButtonClasses}
          >
            <Trash2 className="h-4 w-4" />
            Clear
          </button>
          <button
            onClick={() => setShowShareModal(true)}
            disabled={report.sections.length === 0}
            className={reportActionButtonClasses}
          >
            <Share2 className="h-4 w-4" />
            Share
          </button>
          <div className="ml-auto">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-emerald-500/20 bg-emerald-500/10 text-emerald-500">
              <Sparkles className="h-5 w-5" />
            </div>
          </div>
        </div>

        {/* Report Content */}
        <div ref={reportContentRef} className="flex-1 overflow-y-auto p-8">
          {progressCard ? (
            <ResearchProgressCard
              model={progressCard}
              expanded={progressDetailsOpen}
              onToggleExpanded={() => setProgressDetailsOpen((prev) => !prev)}
              onCancel={activeRun?.status === "running" ? () => void onAnswerNow() : undefined}
              onRetry={activeRun?.status === "failed" ? () => void onRetry() : undefined}
              runId={activeRun?.runId}
            />
          ) : null}

          {report.sections.length === 0 ? (
            <div className="py-20 text-center text-slate-500">
              <div className="mb-4 text-5xl opacity-50">📊</div>
              <p className="text-sm">Your report will appear here</p>
              <p className="mt-2 text-xs text-slate-600">Start a conversation to generate content</p>
            </div>
          ) : (
            report.sections.map((section) => (
              <ReportSectionView
                key={section.id}
                section={section}
                onEdit={handleSectionEdit}
                isHighlighted={highlightedSection === section.id}
              />
            ))
          )}
        </div>
      </div>

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



