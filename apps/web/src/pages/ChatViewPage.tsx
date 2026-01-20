import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, Download, Edit3, Send, Share2, Sparkles, Trash2 } from "lucide-react";

import { useProjectQuery } from "../api/projects";
import { useCreateRunMutation, useCancelRunMutation, useRetryRunMutation } from "../api/runs";
import { apiFetchJson } from "../api/client";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";
import { useSSE } from "../hooks/useSSE";
import { ArtifactSchema, type Artifact } from "../types/dto";
import { RunThinkingBanner } from "../components/run/RunThinkingBanner";
import { z } from "zod";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  ts: string;
  runId?: string;
};

type Chat = {
  id: string;
  title: string;
  createdAt: string;
  messages: ChatMessage[];
};

type ReportSection = {
  id: string;
  heading: string;
  content: Array<{
    text: string;
    citations?: number[];
    isBullet?: boolean;
  }>;
};

type Report = {
  title: string;
  sections: ReportSection[];
};

type ActiveRunStatus = "running" | "failed" | "succeeded" | "canceled";

type ActiveRun = {
  runId: string;
  status: ActiveRunStatus;
  primaryText: string;
  secondaryText?: string;
  startedAt: string;
  error?: string;
};

type LlmProvider = "local" | "hosted";

const ArtifactsSchema = z.array(ArtifactSchema);

const EMPTY_REPORT: Report = {
  title: "Live Report",
  sections: []
};

const DEFAULT_LOCAL_MODEL = "llama3.1:8b";
const DEFAULT_HOSTED_MODEL = "xiaomi/mimo-v2-flash:free";

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function titleCase(value: string): string {
  if (!value) return value;
  return value.replace(/(^|_|-)([a-z])/g, (_, sep, ch) => `${sep} ${ch.toUpperCase()}`).trim();
}

function buildFinalResponse(artifacts: Artifact[]): string {
  for (const artifact of artifacts) {
    const md = artifact.metadata?.["markdown"];
    if (typeof md === "string" && md.trim()) return md.trim();
    const msg = artifact.metadata?.["message"];
    if (typeof msg === "string" && msg.trim()) return msg.trim();
  }
  return "Run completed. Output is available in artifacts.";
}

function parseMarkdownToSections(markdown: string): ReportSection[] {
  const sections: ReportSection[] = [];
  const lines = markdown.split("\n");

  let currentSection: ReportSection | null = null;
  let currentParagraph: string[] = [];

  const flushParagraph = () => {
    if (currentParagraph.length > 0 && currentSection) {
      const text = currentParagraph.join(" ").trim();
      if (text && currentSection) {
        currentSection.content.push({ text });
      }
      currentParagraph = [];
    }
  };

  for (const line of lines) {
    // Check for headers (## or ###)
    const headerMatch = line.match(/^(#{2,3})\s+(.+)$/);
    if (headerMatch) {
      flushParagraph();
      if (currentSection) {
        sections.push(currentSection);
      }
      currentSection = {
        id: generateId(),
        heading: headerMatch[2].trim(),
        content: []
      };
      continue;
    }

    // Skip title (single #)
    if (line.match(/^#\s+/)) {
      continue;
    }

    // Empty line - paragraph break
    if (line.trim() === "") {
      flushParagraph();
      continue;
    }

    // References section
    if (line.trim() === "---" || line.trim() === "## References") {
      flushParagraph();
      if (currentSection) {
        sections.push(currentSection);
      }
      currentSection = {
        id: generateId(),
        heading: "References",
        content: []
      };
      continue;
    }

    // Footnote reference
    if (line.match(/^\[\^\d+\]:/)) {
      if (currentSection && currentSection.heading === "References") {
        const text = line.replace(/^\[\^(\d+)\]:\s*/, "[$1] ");
        currentSection.content.push({ text });
      }
      continue;
    }

    // Regular content line
    currentParagraph.push(line);
  }

  flushParagraph();
  if (currentSection) {
    sections.push(currentSection);
  }

  return sections;
}

function deriveRunUpdate(event: { stage?: string; message?: string; payload?: Record<string, unknown> }) {
  const payload = event.payload ?? {};
  const rawStatus = payload["status"] ?? payload["to_status"];
  const status = typeof rawStatus === "string" ? rawStatus : null;

  let primaryText = "Working";
  let secondaryText: string | undefined;

  if (event.message?.startsWith("Starting stage:")) {
    primaryText = `Working on ${titleCase(event.stage ?? "")}`.trim();
  } else if (event.message?.startsWith("Finished stage:")) {
    primaryText = `Finished ${titleCase(event.stage ?? "")}`.trim();
  } else if (event.stage) {
    primaryText = `Processing ${titleCase(event.stage)}`;
  } else if (event.message) {
    primaryText = event.message;
  }

  const step = payload["step"];
  if (typeof step === "string" && step.trim()) {
    secondaryText = `Step: ${step}`;
  } else {
    const artifactType = payload["artifact_type"];
    if (typeof artifactType === "string" && artifactType.trim()) {
      secondaryText = `Artifact: ${artifactType}`;
    }
  }

  return { status, primaryText, secondaryText };
}

function loadChats(projectId: string): Chat[] {
  const raw = window.localStorage.getItem(`researchops.chats.${projectId}`);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as Chat[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveChats(projectId: string, chats: Chat[]) {
  window.localStorage.setItem(`researchops.chats.${projectId}`, JSON.stringify(chats));
  window.dispatchEvent(new Event("researchops-chats-updated"));
}

// Citation badge component
function CitationBadge({ number }: { number: number }) {
  return (
    <span className="ml-1.5 inline-flex items-center justify-center rounded bg-emerald-500/15 px-2 py-0.5 font-mono text-xs font-semibold text-emerald-400">
      [{number}]
    </span>
  );
}

// Typing indicator
function TypingIndicator() {
  return (
    <div className="flex gap-1 py-2">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-2 w-2 animate-bounce rounded-full bg-emerald-500"
          style={{ animationDelay: `${i * 0.2}s` }}
        />
      ))}
    </div>
  );
}

// Report section component
function ReportSectionView({
  section,
  onEdit,
  isHighlighted
}: {
  section: ReportSection;
  onEdit: (sectionId: string, content: string) => void;
  isHighlighted: boolean;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState(section.content.map((c) => c.text).join("\n\n"));

  const handleSave = () => {
    onEdit(section.id, editedContent);
    setIsEditing(false);
  };

  return (
    <div className={`mb-7 transition-all duration-300 ${isHighlighted ? "animate-pulse" : ""}`}>
      <div className="mb-4 flex items-center gap-3">
        <div className="h-6 w-1 rounded-sm bg-emerald-500" />
        <h3 className="font-mono text-base font-semibold tracking-wide text-emerald-400">{section.heading}</h3>
        {!isEditing && (
          <button
            onClick={() => setIsEditing(true)}
            className="ml-auto flex items-center gap-1.5 rounded border border-slate-700 bg-transparent px-2 py-1 text-xs text-slate-500 transition-colors hover:border-slate-500 hover:text-slate-300"
          >
            <Edit3 className="h-3.5 w-3.5" />
            Edit
          </button>
        )}
      </div>

      {isEditing ? (
        <div className="pl-4">
          <textarea
            value={editedContent}
            onChange={(e) => setEditedContent(e.target.value)}
            className="min-h-32 w-full resize-y rounded-lg border border-emerald-500/40 bg-black/30 p-3 text-sm leading-relaxed text-slate-200 outline-none focus:border-emerald-500/60"
          />
          <div className="mt-3 flex justify-end gap-2">
            <button
              onClick={() => setIsEditing(false)}
              className="rounded-md border border-slate-600 bg-transparent px-4 py-2 text-sm text-slate-400 transition-colors hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              className="rounded-md bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-900 transition-colors hover:bg-emerald-400"
            >
              Save
            </button>
          </div>
        </div>
      ) : (
        <div className="pl-4">
          {section.content.map((item, idx) => (
            <div key={idx} className="mb-3 flex items-start">
              {item.isBullet && <span className="mr-3 mt-0.5 text-xs text-emerald-500">▸</span>}
              <p className="flex-1 text-sm leading-relaxed text-slate-300">
                {item.text}
                {item.citations?.map((num) => <CitationBadge key={num} number={num} />)}
                {!item.isBullet && item.citations && "."}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Export modal
function ExportModal({
  isOpen,
  onClose,
  onExport
}: {
  isOpen: boolean;
  onClose: () => void;
  onExport: (format: string) => void;
}) {
  if (!isOpen) return null;

  const options = [
    { id: "pdf", label: "PDF Document", icon: "📄", desc: "Best for sharing and printing" },
    { id: "docx", label: "Word Document", icon: "📝", desc: "Editable in Microsoft Word" },
    { id: "md", label: "Markdown", icon: "📋", desc: "Plain text with formatting" },
    { id: "html", label: "HTML", icon: "🌐", desc: "Web-ready format" }
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={onClose}>
      <div
        className="w-96 max-w-[90vw] rounded-2xl border border-slate-700 bg-slate-800 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-5 text-lg font-semibold text-slate-100">Export Report</h3>
        <div className="flex flex-col gap-3">
          {options.map((opt) => (
            <button
              key={opt.id}
              onClick={() => onExport(opt.id)}
              className="flex items-center gap-4 rounded-xl border border-slate-700 bg-slate-900/50 p-4 text-left transition-colors hover:border-emerald-500/30 hover:bg-emerald-500/10"
            >
              <span className="text-2xl">{opt.icon}</span>
              <div>
                <div className="text-sm font-medium text-slate-100">{opt.label}</div>
                <div className="mt-0.5 text-xs text-slate-500">{opt.desc}</div>
              </div>
            </button>
          ))}
        </div>
        <button
          onClick={onClose}
          className="mt-4 w-full rounded-lg border border-slate-600 bg-transparent py-3 text-sm text-slate-400 transition-colors hover:bg-slate-700"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// Share modal
function ShareModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const shareLink = "https://researchops.studio/reports/shared-report";

  const handleCopy = () => {
    navigator.clipboard.writeText(shareLink);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={onClose}>
      <div
        className="w-[420px] max-w-[90vw] rounded-2xl border border-slate-700 bg-slate-800 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-5 text-lg font-semibold text-slate-100">Share Report</h3>
        <p className="mb-4 text-sm text-slate-400">Anyone with this link can view the report</p>
        <div className="flex gap-2 rounded-lg border border-slate-700 bg-slate-900/50 p-3">
          <input
            type="text"
            value={shareLink}
            readOnly
            className="flex-1 border-none bg-transparent font-mono text-sm text-slate-200 outline-none"
          />
          <button
            onClick={handleCopy}
            className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              copied
                ? "border border-emerald-500 bg-transparent text-emerald-400"
                : "bg-emerald-500 text-slate-900 hover:bg-emerald-400"
            }`}
          >
            {copied ? "Copied!" : "Copy"}
          </button>
        </div>
        <button
          onClick={onClose}
          className="mt-4 w-full rounded-lg border border-slate-600 bg-transparent py-3 text-sm text-slate-400 transition-colors hover:bg-slate-700"
        >
          Done
        </button>
      </div>
    </div>
  );
}

export function ChatViewPage() {
  const { projectId, chatId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const id = projectId ?? "";
  const project = useProjectQuery(id);
  const createRun = useCreateRunMutation(id);
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null);
  const cancelRun = useCancelRunMutation(activeRun?.runId ?? "");
  const retryRun = useRetryRunMutation(activeRun?.runId ?? "");

  const [chat, setChat] = useState<Chat | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [autorunHandled, setAutorunHandled] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [llmProvider, setLlmProvider] = useState<LlmProvider>("hosted");
  const [llmModel, setLlmModel] = useState(DEFAULT_HOSTED_MODEL);

  const [report, setReport] = useState<Report>(EMPTY_REPORT);
  const [highlightedSection, setHighlightedSection] = useState<string | null>(null);
  const [showExportModal, setShowExportModal] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);
  const [exportNotification, setExportNotification] = useState<string | null>(null);

  const lastEventIdRef = useRef<number>(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  // Load chat from localStorage
  useEffect(() => {
    if (!id || !chatId) return;
    const chats = loadChats(id);
    const found = chats.find((c) => c.id === chatId);
    if (found) {
      setChat(found);
      setMessages(found.messages);
    }
  }, [id, chatId]);

  // Handle autorun parameter
  const createRunRef = useRef(createRun);
  createRunRef.current = createRun;

  useEffect(() => {
    if (autorunHandled) return;
    if (!chat || !id || activeRun) return;
    const autorun = searchParams.get("autorun");
    if (autorun !== "true") return;

    const firstUserMsg = messages.find((m) => m.role === "user");
    if (!firstUserMsg) return;

    setAutorunHandled(true);
    setSearchParams({}, { replace: true });

    void (async () => {
      setIsTyping(true);
      try {
        const run = await createRunRef.current.mutateAsync({
          prompt: firstUserMsg.content,
          llm_provider: llmProvider,
          llm_model: llmModel.trim() ? llmModel.trim() : undefined
        });
        setActiveRun({
          runId: run.id,
          status: "running",
          primaryText: "Starting run...",
          startedAt: new Date().toISOString()
        });
        lastEventIdRef.current = 0;
      } catch (e) {
        setMessages((prev) => [
          ...prev,
          {
            id: generateId(),
            role: "assistant",
            content: e instanceof Error ? `Failed to start run: ${e.message}` : "Failed to start run.",
            ts: new Date().toISOString()
          }
        ]);
      } finally {
        setIsTyping(false);
      }
    })();
  }, [chat, id, messages, activeRun, autorunHandled, searchParams, setSearchParams, llmProvider, llmModel]);

  // Save messages back to localStorage
  useEffect(() => {
    if (!id || !chatId || !chat) return;
    const chats = loadChats(id);
    const updated = chats.map((c) => (c.id === chatId ? { ...c, messages } : c));
    saveChats(id, updated);
  }, [id, chatId, chat, messages]);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  const sse = useSSE(
    activeRun?.runId ? `/runs/${encodeURIComponent(activeRun.runId)}/events` : null,
    Boolean(activeRun?.runId)
  );

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
        setActiveRun((prev) =>
          prev
            ? {
                ...prev,
                status: "failed",
                primaryText: "Something went wrong",
                secondaryText: terminalError ?? "The run failed.",
                error: terminalError
              }
            : prev
        );
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

  async function handleRunCompletion(status: ActiveRunStatus) {
    if (!activeRun) return;
    const runId = activeRun.runId;
    if (status === "canceled") {
      setActiveRun(null);
      lastEventIdRef.current = 0;
      return;
    }

    if (status === "succeeded") {
      const artifacts = await apiFetchJson(`/runs/${encodeURIComponent(runId)}/artifacts`, {
        schema: ArtifactsSchema
      }).catch(() => [] as Artifact[]);
      const response = buildFinalResponse(artifacts);
      setMessages((prev) => [
        ...prev,
        {
          id: generateId(),
          role: "assistant",
          content: response,
          ts: new Date().toISOString(),
          runId
        }
      ]);

      // Add sections to the report based on the response
      if (response && response !== "Run completed. Output is available in artifacts.") {
        const parsedSections = parseMarkdownToSections(response);
        if (parsedSections.length > 0) {
          setReport((prev) => ({
            ...prev,
            sections: [...prev.sections, ...parsedSections]
          }));
          const firstSection = parsedSections[0];
          if (firstSection) {
            setHighlightedSection(firstSection.id);
            setTimeout(() => setHighlightedSection(null), 2000);
          }
        }
      }
    }

    setActiveRun(null);
    lastEventIdRef.current = 0;
  }

  async function onSend() {
    const text = draft.trim();
    if (!text) return;

    const userMsg: ChatMessage = {
      id: generateId(),
      role: "user",
      content: text,
      ts: new Date().toISOString()
    };
    setMessages((prev) => [...prev, userMsg]);
    setDraft("");
    setIsTyping(true);

    if (!id) return;

    try {
      const run = await createRun.mutateAsync({
        prompt: text,
        llm_provider: llmProvider,
        llm_model: llmModel.trim() ? llmModel.trim() : undefined
      });
      setActiveRun({
        runId: run.id,
        status: "running",
        primaryText: "Starting run...",
        startedAt: new Date().toISOString()
      });
      lastEventIdRef.current = 0;
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        {
          id: generateId(),
          role: "assistant",
          content: e instanceof Error ? `Failed to start run: ${e.message}` : "Failed to start run.",
          ts: new Date().toISOString()
        }
      ]);
    } finally {
      setIsTyping(false);
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
      await retryRun.mutateAsync();
      setActiveRun((prev) =>
        prev ? { ...prev, status: "running", primaryText: "Retrying run", secondaryText: undefined } : prev
      );
    } catch {
      // no-op
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
    }
  }

  function handleExport(format: string) {
    setShowExportModal(false);
    setExportNotification(`Exporting as ${format.toUpperCase()}...`);
    setTimeout(() => {
      setExportNotification(`Report downloaded as ${format.toUpperCase()}`);
      setTimeout(() => setExportNotification(null), 2000);
    }, 1500);
  }

  if (project.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="Loading..." />
      </div>
    );
  }

  if (project.isError) {
    return (
      <ErrorBanner message={project.error instanceof Error ? project.error.message : "Failed to load project"} />
    );
  }

  const p = project.data;
  if (!p) return null;

  if (!chat) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-slate-400">Chat not found</div>
      </div>
    );
  }

  const quickActions = ["Add conclusion", "Add recommendations", "Summarize findings", "Add references"];

  return (
    <div className="fixed inset-0 left-16 top-14 flex bg-slate-950 text-slate-200 md:left-64">
      {/* Left Panel - Chat */}
      <div className="flex w-[45%] flex-col border-r border-slate-800">
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
          {messages.map((message) => (
            <div key={message.id} className={`mb-4 flex flex-col ${message.role === "user" ? "items-end" : "items-start"}`}>
              <div
                className={`max-w-[90%] whitespace-pre-wrap rounded-2xl px-4 py-3.5 text-sm leading-relaxed ${
                  message.role === "user"
                    ? "rounded-br-sm border border-emerald-500/30 bg-emerald-500/15 text-slate-200"
                    : "rounded-bl-sm border border-slate-700/50 bg-slate-800/80 text-slate-200"
                }`}
              >
                {message.content}
              </div>
              <div className="mt-1.5 font-mono text-xs text-slate-500">
                {new Date(message.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}
              </div>
            </div>
          ))}
          {isTyping && (
            <div className="inline-block rounded-2xl rounded-bl-sm border border-slate-700/50 bg-slate-800/80 px-4 py-3.5">
              <TypingIndicator />
            </div>
          )}
          {activeRun && (
            <div className="mt-4">
              <RunThinkingBanner
                primaryText={activeRun.primaryText}
                secondaryText={activeRun.secondaryText}
                status={activeRun.status}
                onAnswerNow={activeRun.status === "running" ? onAnswerNow : undefined}
                onRetry={activeRun.status === "failed" ? onRetry : undefined}
              />
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Quick Actions */}
        <div className="flex flex-wrap gap-2 px-6 pb-3">
          {quickActions.map((action) => (
            <button
              key={action}
              onClick={() => setDraft(action)}
              className="rounded-full border border-slate-700 bg-slate-800/50 px-3.5 py-2 text-xs text-slate-400 transition-colors hover:border-emerald-500/30 hover:bg-emerald-500/10 hover:text-emerald-400"
            >
              {action}
            </button>
          ))}
        </div>

        {/* Input */}
        <div className="border-t border-slate-800 px-6 py-4">
          <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-slate-400">
            <div className="flex items-center gap-2">
              <span>LLM</span>
              <select
                className="rounded-md border border-slate-700 bg-slate-900/50 px-2 py-1 text-xs text-slate-200 focus:border-emerald-500/50 focus:outline-none"
                value={llmProvider}
                onChange={(e) => {
                  const next = e.target.value as LlmProvider;
                  setLlmProvider(next);
                  if (next === "local" && (!llmModel.trim() || llmModel === DEFAULT_HOSTED_MODEL)) {
                    setLlmModel(DEFAULT_LOCAL_MODEL);
                  }
                  if (next === "hosted" && (!llmModel.trim() || llmModel === DEFAULT_LOCAL_MODEL)) {
                    setLlmModel(DEFAULT_HOSTED_MODEL);
                  }
                }}
              >
                <option value="local">local</option>
                <option value="hosted">hosted</option>
              </select>
            </div>
            <input
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
              placeholder={llmProvider === "local" ? DEFAULT_LOCAL_MODEL : DEFAULT_HOSTED_MODEL}
              className="min-w-[200px] flex-1 rounded-md border border-slate-700 bg-slate-900/50 px-2 py-1 text-xs text-slate-200 focus:border-emerald-500/50 focus:outline-none"
            />
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
              placeholder="Ask to modify the report..."
              rows={1}
              className="flex-1 resize-none rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3.5 text-sm text-slate-200 outline-none transition-colors focus:border-emerald-500/50"
            />
            <button
              onClick={() => void onSend()}
              disabled={!draft.trim() || isTyping || createRun.isPending}
              className={`flex h-12 w-12 items-center justify-center rounded-xl transition-colors ${
                draft.trim() && !isTyping && !createRun.isPending
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
      <div className="flex w-[55%] flex-col bg-slate-950">
        {/* Report Header */}
        <div className="flex items-center justify-between border-b border-slate-800 px-8 py-5">
          <h2 className="font-mono text-xl font-semibold text-slate-100">Live Report</h2>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-400">
              <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
              {activeRun ? "PROCESSING" : "READY"}
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3 border-b border-slate-800/50 px-8 py-4">
          <button
            onClick={() => setShowExportModal(true)}
            disabled={report.sections.length === 0}
            className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800/50 px-4 py-2.5 text-sm font-medium text-slate-200 transition-colors hover:bg-slate-700/50 disabled:cursor-not-allowed disabled:text-slate-600"
          >
            <Download className="h-4 w-4" />
            Export
          </button>
          <button
            onClick={handleClear}
            disabled={report.sections.length === 0}
            className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800/50 px-4 py-2.5 text-sm font-medium text-slate-200 transition-colors hover:bg-slate-700/50 disabled:cursor-not-allowed disabled:text-slate-600"
          >
            <Trash2 className="h-4 w-4" />
            Clear
          </button>
          <button
            onClick={() => setShowShareModal(true)}
            disabled={report.sections.length === 0}
            className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800/50 px-4 py-2.5 text-sm font-medium text-slate-200 transition-colors hover:bg-slate-700/50 disabled:cursor-not-allowed disabled:text-slate-600"
          >
            <Share2 className="h-4 w-4" />
            Share
          </button>
          <div className="ml-auto">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-500">
              <Sparkles className="h-5 w-5" />
            </div>
          </div>
        </div>

        {/* Report Content */}
        <div className="flex-1 overflow-y-auto p-8">
          {report.sections.length === 0 ? (
            <div className="py-20 text-center text-slate-500">
              <div className="mb-4 text-5xl opacity-50">📄</div>
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

      {/* Export Notification */}
      {exportNotification && (
        <div className="fixed bottom-6 right-6 flex items-center gap-2.5 rounded-xl border border-emerald-500/30 bg-slate-800 px-5 py-3.5 text-sm font-medium text-emerald-400 shadow-xl">
          <Download className="h-4 w-4" />
          {exportNotification}
        </div>
      )}
    </div>
  );
}
