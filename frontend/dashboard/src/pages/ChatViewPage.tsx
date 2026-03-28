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
  // TECH: Read route params from URL; these identify current project and conversation.
  // PLAIN: Get which project and chat we???re looking at from the web address.
  const { projectId, chatId } = useParams();

  // TECH: useLocation provides access to navigation state (e.g., initialMessage passed from previous screen).
  // PLAIN: Lets this page read extra info passed when coming here.
  const location = useLocation();

  // TECH: useNavigate enables imperative navigation (back to project page, etc.).
  // PLAIN: Lets us jump to another page when a button is clicked.
  const navigate = useNavigate();

  // TECH: Normalize project ID to empty string if undefined for hook usage.
  // PLAIN: Make sure we always have a string ID to use.
  const id = projectId ?? "";

  // TECH: Fetch project data; provides isLoading/isError/data.
  // PLAIN: Load the project details so we can show its name.
  const project = useProjectQuery(id);

  // TECH: Fetch up to 200 conversations for the project (pagination/limit provided by hook).
  // PLAIN: Load the list of chats so we can find the current one.
  const conversations = useChatConversationsQuery(id, 200);

  // TECH: Fetch messages using cursor pagination (infinite query).
  // PLAIN: Load the messages in this chat, page-by-page.
  const messagesQuery = useChatMessagesInfiniteQuery(chatId ?? "", 200);

  // TECH: Mutation for sending a message to the server (async).
  // PLAIN: A function that sends what the user typed.
  const sendChat = useSendChatMessageMutationInfinite(chatId ?? "", 200, {
    onStatus: () => setWebSearching(true),
  });

  // TECH: activeRun holds live status of background report job started by assistant.
  // PLAIN: Tracks whether the report is currently being generated.
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null);

  // TECH: Cancel and retry mutations depend on activeRun.runId; empty string if none.
  // PLAIN: Prepare buttons to stop or retry the report job.
  const cancelRun = useCancelRunMutation(activeRun?.runId ?? "");
  const retryRun = useRetryRunMutation(activeRun?.runId ?? "");

  // TECH: draft is controlled textarea value for the chat input.
  // PLAIN: Stores what the user is typing before sending.
  const [draft, setDraft] = useState("");

  // TECH: isTyping indicates we are waiting for server response to sendChat; drives typing indicator.
  // PLAIN: Shows a ???working??? animation so user knows something is happening.
  const [isTyping, setIsTyping] = useState(false);

  const [webSearching, setWebSearching] = useState(false);

  // TECH: selectedModel/customModel track dropdown vs custom model selection.
  // PLAIN: Lets the user pick a model from the list or type a custom one.
  const [selectedModel, setSelectedModel] = useState(DEFAULT_HOSTED_MODEL);
  const [customModel, setCustomModel] = useState("");
  const [showRunModal, setShowRunModal] = useState(false);
  const [pendingDraft, setPendingDraft] = useState<string | null>(null);

  // TECH: runPipelineArmed toggles auto-accepting research pipeline offers.
  // PLAIN: When on, the app auto-starts a research report if offered.
  // Initialised from navigation state so "Run research report" on project page carries through.
  const [runPipelineArmed, setRunPipelineArmed] = useState(() => {
    if (!location.state || typeof location.state !== "object") return false;
    const state = location.state as { runPipeline?: boolean };
    return state.runPipeline === true;
  });

  // TECH: report stores the right-panel report structure.
  // PLAIN: Holds the generated report content that shows on the right side.
  const [report, setReport] = useState<Report>(EMPTY_REPORT);
  const [completedRunArtifacts, setCompletedRunArtifacts] = useState<Record<string, Artifact[]>>({});

  // TECH: reportChatIdRef tracks which chatId the report state currently corresponds to.
  // PLAIN: Prevents saving a report under the wrong conversation when switching chats.
  const reportChatIdRef = useRef<string | null>(null);

  // TECH: highlightedSection temporarily highlights newly added section for UX feedback.
  // PLAIN: Makes new content briefly stand out so user notices it.
  const [highlightedSection, setHighlightedSection] = useState<string | null>(null);

  // TECH: Controls visibility for export/share modals.
  // PLAIN: Tracks whether the popups are open.
  const [showExportModal, setShowExportModal] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);

  // TECH: exportNotification shows a temporary toast message for export status.
  // PLAIN: Shows a message like ???Exporting?????? or ???Downloaded!???
  const [exportNotification, setExportNotification] = useState<string | null>(null);
  const [progressDetailsOpen, setProgressDetailsOpen] = useState(false);

  // TECH: lastEventIdRef deduplicates SSE events by monotonic ID to avoid reprocessing on reconnect.
  // PLAIN: Remembers the latest progress update so we don???t apply the same update twice.
  const lastEventIdRef = useRef<number>(0);

  // TECH: debounceRef is used to throttle rapid SSE updates to reduce re-renders.
  // PLAIN: Prevents the screen from updating too rapidly and looking jittery.
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const highlightTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // TECH: runStatusCheckRef throttles status lookups when SSE drops.
  // PLAIN: Avoids repeatedly polling the server if the stream fails.
  const runStatusCheckRef = useRef<number>(0);

  // TECH: messagesEndRef points to a dummy element at bottom of chat to scroll into view.
  // PLAIN: Helps auto-scroll the chat to the newest message.
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  // TECH: reportContentRef points to the scrollable report panel div so we can scroll it to top.
  // PLAIN: Lets us scroll the report panel back to the top when a new run starts.
  const reportContentRef = useRef<HTMLDivElement | null>(null);

  // TECH: initialMessage can be passed through navigation state to auto-send a first message.
  // PLAIN: Sometimes we arrive here with a message already chosen to send.
  const initialMessage = useMemo(() => {
    // TECH: location.state can be null/unknown type; guard before reading properties.
    // PLAIN: Make sure the extra data exists before using it.
    if (!location.state || typeof location.state !== "object") return null;

    // TECH: Type assertion to expected shape from navigation.
    // PLAIN: Treat the state like it might contain an initial message.
    const state = location.state as { initialMessage?: string };

    // TECH: Return string or null if missing.
    // PLAIN: Use it if present; otherwise there is no initial message.
    return state.initialMessage ?? null;
  }, [location.state]);

  // TECH: Prevents sending initial message multiple times (React effects can run more than once in dev).
  // PLAIN: Makes sure the auto-message is only sent once.
  const initialMessageSentRef = useRef(false);

  // TECH: Find the current chat object from the conversations list.
  // PLAIN: From all chats, pick the one matching the URL.
  const chat = useMemo(() => {
    const items = conversations.data?.items ?? [];
    return items.find((item) => item.id === chatId) ?? null;
  }, [conversations.data, chatId]);

  // TECH: Flatten paginated pages into one list for rendering.
  // PLAIN: Turn pages into a single message list.
  const messages = flattenInfiniteMessages(messagesQuery.data);
  const latestRunId = useMemo(() => extractLatestRunId(messages), [messages]);
  const allRunIds = useMemo(() => extractAllRunIds(messages), [messages]);
  const runHydrationRef = useRef<{ chatId: string | null; runId: string | null }>({
    chatId: null,
    runId: null
  });
  // TECH: Tracks which run IDs have already had an artifact fetch attempted (to avoid re-fetching).
  const hydratedRunArtifactsRef = useRef<Set<string>>(new Set());

  // TECH: Build topbar actions for share/export.
  // PLAIN: Put Share and Export buttons in the header.
  // TECH: Restore saved report whenever the conversation changes.
  // PLAIN: When you open a chat, bring back its last report.
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

  // TECH: Persist report updates so reopening the chat shows the latest report.
  // PLAIN: Save report changes automatically.
  useEffect(() => {
    if (!chatId) return;
    if (reportChatIdRef.current !== chatId) return;
    persistReport(chatId, report);
  }, [chatId, report]);

  // TECH: Effect to auto-send initialMessage once when page loads with that state.
  // PLAIN: If we arrived with a pre-filled message, send it automatically.
  useEffect(() => {
    // TECH: Only run when initialMessage exists, chatId exists, and not already sent.
    // PLAIN: Only send once, and only if we actually have a message and a chat.
    if (!initialMessage || !chatId || initialMessageSentRef.current) return;

    // TECH: Mark sent before awaiting to avoid double-send due to re-renders.
    // PLAIN: Lock it immediately so it doesn???t send twice.
    initialMessageSentRef.current = true;

    // TECH: Clear navigation state so refresh/back doesn't re-send.
    // PLAIN: Remove the "auto send" flag after first use.
    navigate(location.pathname, { replace: true, state: {} });

    // TECH: When pipeline is armed (runPipeline nav state), show model-selection modal
    // instead of auto-sending, so the user can configure per-stage models.
    if (runPipelineArmed) {
      setPendingDraft(initialMessage);
      setShowRunModal(true);
      return;
    }

    // TECH: Fire-and-forget sendMessage; catch errors to avoid unhandled promise rejection.
    // PLAIN: Send it in the background; ignore failures here.
    void sendMessage(initialMessage).catch(() => {});
  }, [initialMessage, chatId, location.pathname, navigate, runPipelineArmed]);

  // Scroll to bottom when messages change
  // TECH: Auto-scroll chat window when a new message arrives (messages.length changes).
  // PLAIN: Keep the newest message visible automatically.
  useEffect(() => {
    // TECH: Use ref to scroll to the sentinel element at bottom.
    // PLAIN: Scroll to the invisible ???bottom marker.???
    const node = messagesEndRef.current;
    if (node && typeof node.scrollIntoView === "function") {
      node.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages.length]);

  // TECH: Setup SSE stream only when there is an activeRun; URL is run-specific.
  // PLAIN: Listen for live progress updates only while a report job is running.
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

  // TECH: Scroll report panel to top when a new run starts so the progress card is visible.
  // PLAIN: When a new report job begins, jump to the top of the report area to show progress.
  useEffect(() => {
    if (!activeRun?.runId) return;
    reportContentRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [activeRun?.runId]);

  // TECH: Load artifacts for every completed run in the chat history, not just the latest.
  // PLAIN: Makes sure download links appear for all past runs, not just the most recent one.
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

  // TECH: Apply incoming SSE events to update activeRun UI and detect terminal status.
  // PLAIN: Update the ???progress banner??? as new updates arrive.
  useEffect(() => {
    // TECH: If no active run, there???s nothing to update.
    // PLAIN: If no job is running, ignore streaming updates.
    if (!activeRun) return;

    // TECH: If there are no SSE events yet, nothing to do.
    // PLAIN: If we haven???t received updates, don???t change anything.
    if (sse.events.length === 0) return;

    // TECH: Filter events to only those with ID greater than last processed to avoid duplicates.
    // PLAIN: Only handle brand new updates.
    const fresh = sse.events.filter((evt) => {
      // TECH: SSE hook includes an id field; default to 0 if missing.
      // PLAIN: Each update may have an identifier; use it if available.
      const idValue = (evt as { id?: number }).id ?? 0;

      // TECH: Skip events that were already applied.
      // PLAIN: Ignore repeats.
      if (idValue <= lastEventIdRef.current) return false;

      // TECH: Update last seen ID; ensures monotonic progress.
      // PLAIN: Remember the newest update number.
      lastEventIdRef.current = Math.max(lastEventIdRef.current, idValue);
      return true;
    });

    // TECH: If nothing fresh, stop.
    // PLAIN: If no new updates, do nothing.
    if (fresh.length === 0) return;

    // TECH: terminal indicates run ended; stored after scanning events.
    // PLAIN: Track if the job finished (success/fail/canceled).
    let terminal: ActiveRunStatus | null = null;

    // TECH: Preserve an error message if failure occurs.
    // PLAIN: Keep the reason if something went wrong.
    let terminalError: string | undefined;

    // TECH: nextPrimary/nextSecondary store the latest non-terminal status text.
    // PLAIN: Keep the newest progress message to display.
    let nextPrimary: string | undefined;
    let nextSecondary: string | undefined;

    // TECH: Process events in order, allowing later messages to override earlier ones.
    // PLAIN: Read each update and keep the most recent message.
    for (const evt of fresh) {
      const { status, primaryText, secondaryText } = deriveRunUpdate(evt);

      // TECH: Terminal statuses stop the run and trigger completion handling.
      // PLAIN: If the job is finished, we stop showing ???working.???
      if (status && ["succeeded", "failed", "canceled"].includes(status)) {
        terminal = status as ActiveRunStatus;

        // TECH: Capture error message from event for failed state.
        // PLAIN: Save the error text so we can show it.
        if (status === "failed") {
          terminalError = typeof evt.message === "string" ? evt.message : undefined;
        }
      } else {
        // TECH: For non-terminal updates, keep the most recent readable text.
        // PLAIN: Otherwise, update the progress message.
        nextPrimary = primaryText;
        nextSecondary = secondaryText;
      }
    }

    // TECH: Handle terminal state first so we don't show stale "running" UI.
    // PLAIN: If it finished, show the final status.
    if (terminal) {
      if (terminal === "failed") {
        // TECH: Fetch the run record to show the concrete failure reason.
        // PLAIN: Ask the server why it failed so the UI can show the real error.
        void hydrateRunFailure(activeRun.runId, terminalError);
      } else {
        // TECH: For succeeded/canceled, complete run flow (fetch artifacts, update report, cleanup).
        // PLAIN: If it finished successfully, add results to the report; if canceled, stop.
        void handleRunCompletion(terminal);
      }
      return;
    }

    // TECH: If no status message updates, do nothing.
    // PLAIN: If there???s no new text to show, leave it as is.
    if (!nextPrimary) return;

    // TECH: Debounce updates so high-frequency SSE doesn't cause excessive re-renders.
    // PLAIN: Prevent too many quick screen updates.
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
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [activeRun, sse.events]);

  // TECH: If SSE drops, check run status so the UI doesn't hang.
  // PLAIN: When live updates fail, ask the server if the run ended and show the error.
  useEffect(() => {
    if (!activeRun || activeRun.status !== "running") return;
    if (sse.state !== "error" && sse.state !== "closed") return;

    const now = Date.now();
    if (now - runStatusCheckRef.current < 2000) return;
    runStatusCheckRef.current = now;

    void hydrateRunFailure(activeRun.runId, sse.lastError ?? undefined);
  }, [activeRun, sse.state, sse.lastError]);

  // TECH (Function Summary): Handles end-of-run logic: fetches artifacts, parses markdown, updates report, resets run state.
  // PLAIN (Function Summary): When the job finishes, it grabs the final result and adds it into the report view.
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
    // TECH: Must have an activeRun to know runId.
    // PLAIN: If there???s no job, there???s nothing to finish.
    if (!activeRun) return;

    // TECH: Cache runId because activeRun might change during awaits.
    // PLAIN: Save the job ID so we keep using the same one.
    const runId = activeRun.runId;

    // TECH: If canceled, clear UI and reset event tracking.
    // PLAIN: If the user stopped it, remove the progress banner.
    if (status === "canceled") {
      setActiveRun(null);
      lastEventIdRef.current = 0;
      return;
    }

    // TECH: On success, fetch artifacts for this run from the server.
    // PLAIN: If it finished, download the result files from the system.
    if (status === "succeeded") {
      await hydrateReportFromArtifacts(runId);
    }

    // TECH: Cleanup: clear active run and reset last event id so next run starts clean.
    // PLAIN: Reset the ???job running??? state so the UI goes back to normal.
    setActiveRun(null);
    lastEventIdRef.current = 0;
  }

  // TECH (Function Summary): Fetch run status and surface failures immediately in the UI.
  // PLAIN (Function Summary): Ask the server why the run failed and show that reason.
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

  // TECH: If the user reloads/reopens the chat while a run is running (or finished), try to recover it.
  // PLAIN: If you come back later, the page should still show the report (or resume progress).
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

  // TECH (Function Summary): Sends a user message to backend, starts run tracking if assistant responds with run_started.
  // PLAIN (Function Summary): Sends the chat message and starts tracking the report job if one begins.
  async function sendMessage(text: string, stageModels?: StageModels) {
    // TECH: Trim whitespace to avoid sending empty messages.
    // PLAIN: Don???t send blank messages.
    const trimmed = text.trim();
    if (!trimmed || !chatId) return;
    const isAction = trimmed.startsWith("__ACTION__:");
    const modelValue =
      selectedModel === CUSTOM_MODEL_VALUE ? customModel.trim() : selectedModel.trim();

    // TECH: Toggle typing state to show indicator and disable actions.
    // PLAIN: Show that the system is working on your message.
    setIsTyping(true);

    try {
      // TECH: Send message to backend via mutation. Expected response includes assistant_message.
      // PLAIN: Ask the server to process the message and produce a reply.
      const response = await sendChat.mutateAsync({
        conversation_id: chatId,
        project_id: id || undefined,
        message: trimmed,

        // TECH: Client message ID supports idempotency and reconciliation in distributed systems.
        // PLAIN: A unique ID helps prevent duplicates and improves tracking.
        client_message_id: generateClientMessageId(),

        // TECH: Specify provider and model; allows backend to route to hosted LLM.
        // PLAIN: Tell the system which AI model to use.
        llm_provider: "hosted",
        llm_model: modelValue ? modelValue : undefined,
        force_pipeline: runPipelineArmed && !isAction,
        stage_models: stageModels ?? undefined,
      });

      // TECH: Assistant message can be a special type indicating a background run started.
      // PLAIN: The assistant might start a longer job to generate a report.
      const assistant = response.assistant_message;

      if (assistant?.type === "run_started") {
        // TECH: run_id is stored in content_json; validate it???s a string.
        // PLAIN: Get the job ID if one was created.
        const runId = assistant.content_json?.["run_id"];
        const runQuestion = assistant.content_json?.["question"];
        if (typeof runId === "string") {
          // TECH: Set activeRun so SSE starts and banner appears.
          // PLAIN: Show the ???job running??? indicator and start listening for progress.
          setActiveRun({
            runId,
            status: "running",
            question: typeof runQuestion === "string" ? runQuestion : undefined,
            primaryText: "Starting run...",
            startedAt: new Date().toISOString()
          });

          // TECH: Reset event ID tracking so we handle new run events from start.
          // PLAIN: Start progress tracking from zero for this new job.
          lastEventIdRef.current = 0;
        }
      }

    } finally {
      // TECH: Always clear typing indicator even if request fails.
      // PLAIN: Stop showing ???typing??? no matter what happens.
      setIsTyping(false);
      setWebSearching(false);
    }
  }

  // TECH (Function Summary): Sends current draft message; clears draft on success; preserves draft on failure.
  // PLAIN (Function Summary): Sends what you typed, and clears the box if it worked.
  async function onSend() {
    // TECH: Trim to prevent whitespace-only messages.
    // PLAIN: Don???t send empty messages.
    const text = draft.trim();
    if (!text) return;

    // TECH: When pipeline is armed, show model-selection modal before sending.
    // PLAIN: If you???re about to run a report, pick the models first.
    if (runPipelineArmed) {
      setPendingDraft(text);
      setShowRunModal(true);
      return;
    }

    try {
      // TECH: Await sendMessage so we know when it's done.
      // PLAIN: Send it and wait for the server to accept it.
      await sendMessage(text);

      // TECH: Clear input after successful send for UX.
      // PLAIN: Empty the text box after sending.
      setDraft("");
      setRunPipelineArmed(false);
    } catch {
      // TECH: Intentionally keep draft for retry; swallowing error avoids UI crash.
      // PLAIN: If it fails, keep your message so you can try again.
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

  // TECH (Function Summary): Requests canceling the current run; updates banner status.
  // PLAIN (Function Summary): Stops the report job if it???s running.
  async function onAnswerNow() {
    // TECH: Only possible if a run exists.
    // PLAIN: If there???s no job running, there???s nothing to stop.
    if (!activeRun) return;

    try {
      // TECH: Cancel mutation triggers backend to stop work (best-effort).
      // PLAIN: Tell the server to stop generating the report.
      await cancelRun.mutateAsync();

      // TECH: Optimistically update banner to ???stopping??? for immediate feedback.
      // PLAIN: Immediately show ???stopping??? so the user sees something happen.
      setActiveRun((prev) => (prev ? { ...prev, primaryText: "Stopping run..." } : prev));
    } catch {
      // TECH: If cancel fails, clear run state anyway to unblock UI.
      // PLAIN: If stopping doesn???t work, remove the banner so the UI isn???t stuck.
      setActiveRun(null);
    }
  }

  // TECH (Function Summary): Retries the current run using retry mutation and resets banner text.
  // PLAIN (Function Summary): Tries the report job again if it failed.
  async function onRetry() {
    // TECH: Only retry when we have a run ID.
    // PLAIN: Can only retry if a job exists.
    if (!activeRun) return;

    try {
      // TECH: Ask backend to restart or re-queue the run.
      // PLAIN: Tell the server to try again.
      const modelValue =
        selectedModel === CUSTOM_MODEL_VALUE ? customModel.trim() : selectedModel.trim();
      await retryRun.mutateAsync(modelValue || undefined);

      // TECH: Reset UI state to running.
      // PLAIN: Show that the job is working again.
      setActiveRun((prev) =>
        prev ? { ...prev, status: "running", primaryText: "Retrying run", secondaryText: undefined } : prev
      );
    } catch {
      // TECH: no-op to avoid surfacing errors here; banner remains.
      // PLAIN: If retry fails, do nothing extra.
    }
  }

  // TECH (Function Summary): Updates the report by replacing the matching section with new plain text content.
  // PLAIN (Function Summary): Saves edits made to a specific report section.
  function handleSectionEdit(sectionId: string, newContent: string) {
    // TECH: Immutable update to preserve React state patterns; map replaces only the targeted section.
    // PLAIN: Update only the one section that was edited, leaving the rest unchanged.
    setReport((prev) => ({
      ...prev,
      sections: prev.sections.map((s) => (s.id === sectionId ? { ...s, content: [{ text: newContent }] } : s))
    }));
  }

  // TECH (Function Summary): Clears the report after confirmation.
  // PLAIN (Function Summary): Deletes the report text from the right panel (with a safety prompt).
  function handleClear() {
    // TECH: window.confirm prevents accidental destructive action.
    // PLAIN: Ask ???are you sure???? before deleting content.
    if (window.confirm("Are you sure you want to clear the report?")) {
      setReport(EMPTY_REPORT);
      if (chatId) {
        persistReport(chatId, EMPTY_REPORT);
      }
    }
  }

  // TECH (Function Summary): Handles export flow for multiple formats and shows notifications for progress/errors.
  // PLAIN (Function Summary): Downloads the report in the chosen format and shows a message about it.
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

  // TECH: Loading state for project query; show spinner to avoid rendering incomplete UI.
  // PLAIN: While the project is loading, show a loading indicator.
  if (project.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="Loading..." />
      </div>
    );
  }

  // TECH: Error state for project query; show error banner with message.
  // PLAIN: If the project can???t load, show an error message.
  if (project.isError) {
    return <ErrorBanner message={project.error instanceof Error ? project.error.message : "Failed to load project"} />;
  }

  // TECH: Extract loaded project data.
  // PLAIN: Get the project info we loaded.
  const p = project.data;
  if (!p) return null;

  // TECH: Loading state for conversations; show spinner until chat list is available.
  // PLAIN: While chats are loading, show a loading indicator.
  if (conversations.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="Loading conversation..." />
      </div>
    );
  }

  // TECH: If chatId is not found in conversations list, show fallback UI.
  // PLAIN: If the chat doesn???t exist, show ???not found.???
  if (!chat) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-slate-400">Chat not found</div>
      </div>
    );
  }

  // TECH: Quick action presets that write into the draft input for convenience.
  // PLAIN: Shortcuts you can click to quickly ask common requests.
  const quickActions = ["Add conclusion", "Add recommendations", "Summarize findings", "Add references"];
  const reportActionButtonClasses =
    "inline-flex h-11 shrink-0 items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-4 text-sm font-medium text-slate-200 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:text-slate-600";

  return (
    // TECH: Two-panel fixed layout; left is chat, right is report preview.
    // PLAIN: Split screen with chat on the left and report on the right.
    <div className="flex h-full min-h-0 bg-slate-950 text-slate-200">
      {/* Left Panel - Chat */}
      {/* TECH: Left panel is chat column with header, message list, quick actions, and input area. */}
      {/* PLAIN: This is where you talk to the assistant. */}
      <div className="flex w-[45%] min-h-0 flex-col border-r border-slate-800">
        {/* Chat Header */}
        {/* TECH: Header shows back navigation and chat/project metadata. */}
        {/* PLAIN: Top bar with a back button and the chat name. */}
        <div className="border-b border-slate-800 px-6 py-5">
          <div className="flex items-center gap-3">
            <button
              // TECH: Navigates back to the project page.
              // PLAIN: Takes you back to the project screen.
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
        {/* TECH: Scrollable message list; maps message DTOs to styled bubbles with special cases for offers/errors/run links. */}
        {/* PLAIN: All chat messages are shown here, like in a messaging app. */}
        <div className="flex-1 overflow-y-auto p-6">
          {messages.map((message) => {
            // TECH: Determine styling and behavior based on message role/type.
            // PLAIN: Decide how to display each message.
            const isUser = message.role === "user";
            const isOffer = message.type === "pipeline_offer";
            const isRunStarted = message.type === "run_started";
            const isError = message.type === "error";

            // TECH: Extract run ID for ???open run viewer??? link from run_started message JSON.
            // PLAIN: If a report job started, grab its ID so we can link to it.
            const runId = isRunStarted ? (message.content_json?.["run_id"] as string | undefined) : undefined;

            // TECH: Pipeline offer actions are stored in message.content_json.offer.actions.
            // PLAIN: Some messages include buttons with suggested actions.
            const offer = message.content_json?.["offer"];

            // TECH: Validate actions structure defensively (API shape can vary).
            // PLAIN: Only use action buttons if they are formatted correctly.
            const actions = Array.isArray((offer as { actions?: unknown[] } | undefined)?.actions)
              ? ((offer as { actions: Array<{ id?: string; label?: string }> }).actions ?? [])
              : [];

            return (
              <div key={message.id} className={`mb-4 flex flex-col ${isUser ? "items-end" : "items-start"}`}>
                <div
                  // TECH: Bubble styling depends on user vs assistant vs error. Only user/error bubbles preserve raw newlines;
                  // assistant markdown uses normal whitespace so blank lines don't compound with markdown block spacing.
                  // PLAIN: The bubble looks different for you, the assistant, and errors.
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
                  {/* TECH: Render markdown for chat text; action messages use friendly labels. */}
                  {/* PLAIN: Show the message with formatting when possible. */}
                  {message.type === "action" ? (
                    <span>{displayMessageText(message)}</span>
                  ) : (
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>
                      {normalizeChatMarkdown(message.content_text)}
                    </ReactMarkdown>
                  )}

                  {/* TECH: If assistant started a run, keep the bubble informational only. */}
                  {/* PLAIN: The progress now lives in the report panel, so no separate run page link is shown here. */}
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

                {/* TECH: Render action buttons for pipeline offers; clicking sends a special __ACTION__ message to backend. */}
                {/* PLAIN: Some assistant messages provide quick buttons you can click. */}
                {isOffer && actions.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {actions.map((action) => (
                      <button
                        key={action.id ?? action.label}
                        onClick={() => {
                          // TECH: Guard against missing action IDs to avoid sending invalid messages.
                          // PLAIN: If there???s no action code, do nothing.
                          if (!action.id) return;

                          // TECH: Send an encoded message; backend interprets __ACTION__ prefix as command.
                          // PLAIN: Send a special command message to trigger that action.
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

                {/* TECH: Timestamp rendering; uses locale formatting with 24-hour time and seconds. */}
                {/* PLAIN: Shows when each message was sent. */}
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

          {/* TECH: Show typing indicator when a message is being sent/processed. */}
          {/* PLAIN: Animated dots show the system is working; text when web search fires. */}
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

          {/* TECH: Sentinel element to scrollIntoView for auto-scrolling. */}
          {/* PLAIN: Invisible marker at the bottom of the chat. */}
          <div ref={messagesEndRef} />
        </div>

        {/* Quick Actions */}
        {/* TECH: Quick action chips fill the draft input for faster prompting. */}
        {/* PLAIN: Click a suggestion to automatically fill the message box. */}
        <div className="flex flex-wrap gap-2 px-6 pb-3">
          {quickActions.map((action) => (
            <button
              key={action}
              // TECH: Set draft text to the selected action template.
              // PLAIN: Put this suggestion into the message box.
              onClick={() => { setDraft(action); setRunPipelineArmed(false); }}
              className="rounded-full border border-slate-700 bg-slate-900 px-3.5 py-2 text-xs text-slate-400 transition-colors hover:border-emerald-500/30 hover:bg-emerald-500/10 hover:text-emerald-400"
            >
              {action}
            </button>
          ))}
        </div>

        {/* Input */}
        {/* TECH: Input area with model selector and textarea; Enter sends, Shift+Enter creates newline. */}
        {/* PLAIN: Where you type your message and choose the AI model. */}
        <div className="border-t border-slate-800 px-6 py-4">
          <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-slate-400">
            <span>LLM model</span>
            <div className="flex flex-1 flex-wrap items-center gap-2">
              <select
                // TECH: Dropdown of known models; custom option opens manual input.
                // PLAIN: Pick a model from the list.
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
                  // TECH: Manual entry for custom model id.
                  // PLAIN: Type a model id if it's not in the list.
                  value={customModel}
                  onChange={(e) => setCustomModel(e.target.value)}
                  placeholder="Enter model id"
                  className="min-w-[220px] flex-1 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-emerald-500/50 focus:outline-none"
                />
              ) : null}
            </div>
            <button
              type="button"
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
              // TECH: Controlled textarea stores current user draft; rows={1} with resize-none mimics chat input.
              // PLAIN: This is the message box where you type.
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                // TECH: Enter submits; Shift+Enter inserts newline. Prevent default to avoid newline on send.
                // PLAIN: Press Enter to send; press Shift+Enter for a new line.
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
              // TECH: Click send triggers onSend; disabled unless valid draft and not busy.
              // PLAIN: Sends your message.
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
      {/* TECH: Right panel displays the live report and related actions (export/clear/share). */}
      {/* PLAIN: This is where your report appears and where you can download/share it. */}
      <div className="flex w-[55%] min-h-0 flex-col bg-slate-950">
        {/* Report Header */}
        {/* TECH: Shows report title and a status pill that reflects whether a run is active. */}
        {/* PLAIN: Top bar showing ???Live Report??? and whether it???s ready or processing. */}
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
        {/* TECH: Report-level actions; disabled when report is empty to prevent meaningless exports/shares. */}
        {/* PLAIN: Buttons to download, clear, or share the report once it exists. */}
        <div className="flex flex-wrap gap-3 border-b border-slate-800 px-8 py-4">
          <button
            // TECH: Open export modal; disabled if no sections.
            // PLAIN: Choose how to download the report.
            onClick={() => setShowExportModal(true)}
            disabled={report.sections.length === 0}
            className={reportActionButtonClasses}
          >
            <Download className="h-4 w-4" />
            Export
          </button>
          <button
            // TECH: Clear report content; disabled if report is empty.
            // PLAIN: Delete the report text from the screen.
            onClick={handleClear}
            disabled={report.sections.length === 0}
            className={reportActionButtonClasses}
          >
            <Trash2 className="h-4 w-4" />
            Clear
          </button>
          <button
            // TECH: Open share modal; disabled if report is empty.
            // PLAIN: Show a share link for the report.
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
        {/* TECH: Conditional rendering shows empty-state when no report sections exist; otherwise renders each section. */}
        {/* PLAIN: If there???s no report yet, show a placeholder; otherwise show the report. */}
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
      {/* TECH: ExportModal and ShareModal are controlled components; rendered based on state booleans. */}
      {/* PLAIN: Popups that appear when needed. */}
      <ExportModal isOpen={showExportModal} onClose={() => setShowExportModal(false)} onExport={handleExport} />
      <ShareModal isOpen={showShareModal} onClose={() => setShowShareModal(false)} />
      <ConfigureRunModal
        open={showRunModal}
        onCancel={() => { setShowRunModal(false); setPendingDraft(null); }}
        onStart={handleStartRun}
      />

      {/* Export Notification */}
      {/* TECH: Toast notification shows export progress/result; disappears after timer in handleExport. */}
      {/* PLAIN: Small message popup in the corner about downloading status. */}
      {exportNotification && (
        <div className="fixed bottom-6 right-6 flex items-center gap-2.5 rounded-xl border border-emerald-500/30 bg-slate-900 px-5 py-3.5 text-sm font-medium text-emerald-400 shadow-xl">
          <Download className="h-4 w-4" />
          {exportNotification}
        </div>
      )}
    </div>
  );
}



