import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { Download } from "lucide-react";
import {
  flattenInfiniteMessages,
  useChatConversationsQuery,
  useChatMessagesInfiniteQuery,
  useSendChatMessageMutationInfinite,
} from "../api/chat";
import { apiFetchJson } from "../api/client";
import { useProjectQuery } from "../api/projects";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { ErrorBoundary } from "../components/ui/ErrorBoundary";
import { Spinner } from "../components/ui/Spinner";
import { ChatComposer } from "../features/chat/components/ChatComposer";
import { ChatMessageList } from "../features/chat/components/ChatMessageList";
import { ChatViewHeader } from "../features/chat/components/ChatViewHeader";
import { MODEL_OPTIONS, CUSTOM_MODEL_VALUE, DEFAULT_HOSTED_MODEL, EMPTY_REPORT } from "../features/chat/constants";
import { ConfigureRunModal, type StageModels } from "../features/chat/components/ConfigureRunModal";
import { ExportModal } from "../features/chat/components/ExportModal";
import { ReportPane } from "../features/chat/components/ReportPane";
import { ShareModal } from "../features/chat/components/ShareModal";
import { generateClientMessageId } from "../features/chat/lib/ids";
import { extractAllRunIds, extractLatestRunId } from "../features/chat/lib/reportArtifacts";
import { useReportHydration } from "../features/chat/hooks/useReportHydration";
import { useRunLifecycle } from "../features/chat/hooks/useRunLifecycle";
import type { ActiveRun } from "../features/chat/types";
import { ArtifactSchema } from "../types/dto";
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

  const [draft, setDraft] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [webSearching, setWebSearching] = useState(false);
  const [selectedModel, setSelectedModel] = useState(DEFAULT_HOSTED_MODEL);
  const [customModel, setCustomModel] = useState("");
  const [showRunModal, setShowRunModal] = useState(false);
  const [pendingDraft, setPendingDraft] = useState<string | null>(null);
  const [showExportModal, setShowExportModal] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);
  const [exportNotification, setExportNotification] = useState<string | null>(null);

  const [runPipelineArmed, setRunPipelineArmed] = useState(() => {
    if (!location.state || typeof location.state !== "object") return false;
    const state = location.state as { runPipeline?: boolean };
    return state.runPipeline === true;
  });

  const sendChat = useSendChatMessageMutationInfinite(chatId ?? "", 200, {
    onStatus: () => setWebSearching(true),
  });

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const reportContentRef = useRef<HTMLDivElement>(null);
  const initialMessageSentRef = useRef(false);
  const hydratedRunArtifactsRef = useRef<Set<string>>(new Set());

  const messages = flattenInfiniteMessages(messagesQuery.data);
  const latestRunId = useMemo(() => extractLatestRunId(messages), [messages]);
  const allRunIds = useMemo(() => extractAllRunIds(messages), [messages]);

  const chat = useMemo(() => {
    const items = conversations.data?.items ?? [];
    return items.find((item) => item.id === chatId) ?? null;
  }, [conversations.data, chatId]);

  const initialMessage = useMemo(() => {
    if (!location.state || typeof location.state !== "object") return null;
    const state = location.state as { initialMessage?: string };
    return state.initialMessage ?? null;
  }, [location.state]);

  // ── Report hydration ──────────────────────────────────────────────────────
  const {
    report,
    setReport,
    highlightedSection,
    completedRunArtifacts,
    setCompletedRunArtifacts,
    hydrateReportFromArtifacts,
    clearReport,
  } = useReportHydration(chatId);

  // ── Run lifecycle (SSE, status polling, cancel/retry) ─────────────────────
  const {
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
  } = useRunLifecycle({
    chatId,
    chatTitle: chat?.title ?? undefined,
    messages,
    latestRunId,
    selectedModel,
    customModel,
    hydrateReportFromArtifacts,
    setCompletedRunArtifacts,
  });

  // Reset hydratedRunArtifacts when chatId changes
  useEffect(() => {
    hydratedRunArtifactsRef.current = new Set();
  }, [chatId]);

  // Scroll to bottom when messages change
  useEffect(() => {
    const node = messagesEndRef.current;
    if (node && typeof node.scrollIntoView === "function") {
      node.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages.length]);

  // Scroll report pane to top on new run
  useEffect(() => {
    if (!activeRun?.runId) return;
    reportContentRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [activeRun?.runId]);

  // Hydrate artifacts for all completed runs in message history
  useEffect(() => {
    if (!chatId) return;

    const toFetch = allRunIds.filter(
      (runId) =>
        runId !== activeRun?.runId && !hydratedRunArtifactsRef.current.has(runId),
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
  }, [chatId, allRunIds, activeRun?.runId, setCompletedRunArtifacts]);

  // Auto-send initial message from navigation state
  useEffect(() => {
    if (!initialMessage || !chatId || initialMessageSentRef.current) return;
    initialMessageSentRef.current = true;
    navigate(location.pathname, { replace: true, state: {} });

    if (runPipelineArmed) {
      setPendingDraft(initialMessage);
      setShowRunModal(true);
      return;
    }

    void sendMessage(initialMessage).catch(() => {});
  }, [initialMessage, chatId, location.pathname, navigate, runPipelineArmed]);

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
            error: runStatus === "blocked" ? blockedMessage : undefined,
          } as ActiveRun);
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

  function handleSectionEdit(sectionId: string, newContent: string) {
    setReport((prev) => ({
      ...prev,
      sections: prev.sections.map((s) =>
        s.id === sectionId ? { ...s, content: [{ text: newContent }] } : s,
      ),
    }));
  }

  function handleClear() {
    if (window.confirm("Are you sure you want to clear the report?")) {
      clearReport();
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
      setExportNotification(
        `Export failed: ${error instanceof Error ? error.message : "Unknown error"}`,
      );
      setTimeout(() => setExportNotification(null), 3000);
    }
  }

  // ── Loading / error states ─────────────────────────────────────────────────
  if (project.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner label="Loading..." />
      </div>
    );
  }

  if (project.isError) {
    return (
      <ErrorBanner
        message={
          project.error instanceof Error ? project.error.message : "Failed to load project"
        }
      />
    );
  }

  const p = project.data;
  if (!p) return null;

  if (conversations.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner label="Loading conversation..." />
      </div>
    );
  }

  if (!chat) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="text-slate-400">Chat not found</div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 min-h-0 bg-slate-950 text-slate-200">
      {/* Left Panel - Chat */}
      <div className="flex w-[45%] min-h-0 flex-col border-r border-slate-800">
        <ChatViewHeader
          chatTitle={chat.title ?? ""}
          projectName={p.name}
          onBack={() => navigate(`/projects/${id}`)}
        />

        <ErrorBoundary>
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
        </ErrorBoundary>
      </div>

      <ErrorBoundary>
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
          onCancel={activeRun?.status === "running" ? () => void onCancelRun() : undefined}
          onRetry={
            activeRun && (activeRun.status === "failed" || activeRun.status === "blocked")
              ? () => void onRetryRun()
              : undefined
          }
          onExport={() => setShowExportModal(true)}
          onClear={handleClear}
          onShare={() => setShowShareModal(true)}
          onSectionEdit={handleSectionEdit}
        />
      </ErrorBoundary>

      {/* Modals */}
      <ExportModal
        isOpen={showExportModal}
        onClose={() => setShowExportModal(false)}
        onExport={handleExport}
      />
      <ShareModal isOpen={showShareModal} onClose={() => setShowShareModal(false)} />
      <ConfigureRunModal
        open={showRunModal}
        onCancel={() => {
          setShowRunModal(false);
          setPendingDraft(null);
        }}
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
