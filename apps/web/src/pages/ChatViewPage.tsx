import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Download, Edit3, Send, Share2, Sparkles, Trash2 } from "lucide-react";
import jsPDF from "jspdf";
import { Document, Paragraph, TextRun, HeadingLevel, Packer } from "docx";
import { saveAs } from "file-saver";

import { useChatConversationsQuery, useChatMessagesQuery, useSendChatMessageMutation } from "../api/chat";
import { useProjectQuery } from "../api/projects";
import { useCancelRunMutation, useRetryRunMutation } from "../api/runs";
import { apiFetchJson } from "../api/client";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";
import { useSSE } from "../hooks/useSSE";
import { ArtifactSchema, type Artifact, type ChatMessage } from "../types/dto";
import { RunThinkingBanner } from "../components/run/RunThinkingBanner";
import { z } from "zod";

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

const ArtifactsSchema = z.array(ArtifactSchema);

const EMPTY_REPORT: Report = {
  title: "Live Report",
  sections: []
};

const DEFAULT_HOSTED_MODEL = "xiaomi/mimo-v2-flash:free";

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function generateClientMessageId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
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

/**
 * ✅ Upgraded markdown parsing
 * Supports:
 * - Headers (##, ###)
 * - Paragraphs (multi-line)
 * - Bullets (-, *, +)
 * - Numbered lists (1. 2. ...)
 * - Inline citations [1] [2] and footnote refs [^3]
 * - References with footnotes [^1]: ...
 * - Multi-line footnotes (indented continuations)
 */
function extractInlineCitations(input: string): { text: string; citations: number[] } {
  const citations: number[] = [];

  // Matches [1], [12], [^3], [^42]
  const citationRegex = /\[(\d+)\]|\[\^(\d+)\]/g;

  const textWithoutCitations = input.replace(citationRegex, (_match, g1, g2) => {
    const numRaw = g1 ?? g2;
    const num = Number(numRaw);
    if (!Number.isNaN(num)) citations.push(num);
    return "";
  });

  const cleaned = textWithoutCitations
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([.,;:!?])/g, "$1")
    .trim();

  const seen = new Set<number>();
  const uniq = citations.filter((n) => {
    if (seen.has(n)) return false;
    seen.add(n);
    return true;
  });

  return { text: cleaned, citations: uniq };
}

function isReferencesHeading(line: string): boolean {
  const normalized = line.trim().toLowerCase();
  return (
    normalized === "## references" ||
    normalized === "## reference" ||
    normalized === "## bibliography" ||
    normalized === "## citations"
  );
}

function parseMarkdownToSections(markdown: string): ReportSection[] {
  const sections: ReportSection[] = [];
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");

  let currentSection: ReportSection | null = null;
  let paragraphBuffer: string[] = [];

  // For multi-line footnotes
  let lastFootnoteIndex: number | null = null;

  const ensureSection = (heading: string) => {
    if (!currentSection) {
      currentSection = {
        id: generateId(),
        heading,
        content: []
      };
    }
  };

  const pushSectionIfAny = () => {
    if (currentSection) {
      sections.push(currentSection);
      currentSection = null;
    }
  };

  const flushParagraph = () => {
    if (!currentSection) return;
    if (paragraphBuffer.length === 0) return;

    const rawText = paragraphBuffer.join(" ").trim();
    paragraphBuffer = [];
    lastFootnoteIndex = null;

    if (!rawText) return;

    const { text, citations } = extractInlineCitations(rawText);
    const finalText = text || rawText;

    if (!finalText) return;

    currentSection.content.push({
      text: finalText,
      citations: citations.length > 0 ? citations : undefined,
      isBullet: false
    });
  };

  const pushBullet = (raw: string) => {
    ensureSection("Live Report");
    flushParagraph();

    const { text, citations } = extractInlineCitations(raw);
    const finalText = text || raw;

    currentSection!.content.push({
      text: finalText,
      citations: citations.length > 0 ? citations : undefined,
      isBullet: true
    });

    lastFootnoteIndex = null;
  };

  const pushReferenceFootnote = (num: number, content: string) => {
    ensureSection("References");
    flushParagraph();

    const formatted = `[${num}] ${content}`.trim();
    currentSection!.content.push({
      text: formatted,
      isBullet: true
    });

    lastFootnoteIndex = currentSection!.content.length - 1;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? "";

    // Headers: ## or ###
    const headerMatch = line.match(/^(#{2,3})\s+(.+)$/);
    if (headerMatch) {
      flushParagraph();
      pushSectionIfAny();

      currentSection = {
        id: generateId(),
        heading: headerMatch[2].trim(),
        content: []
      };

      lastFootnoteIndex = null;
      continue;
    }

    // Ignore title line (# ...)
    if (/^#\s+/.test(line)) {
      continue;
    }

    // References heading
    if (isReferencesHeading(line)) {
      flushParagraph();
      pushSectionIfAny();
      currentSection = {
        id: generateId(),
        heading: "References",
        content: []
      };
      lastFootnoteIndex = null;
      continue;
    }

    // Horizontal rule treated as references separator
    if (line.trim() === "---") {
      flushParagraph();
      pushSectionIfAny();
      currentSection = {
        id: generateId(),
        heading: "References",
        content: []
      };
      lastFootnoteIndex = null;
      continue;
    }

    // Empty line breaks paragraphs
    if (line.trim() === "") {
      flushParagraph();
      continue;
    }

    // Footnote definition: [^1]: ...
    const footnoteMatch = line.match(/^\[\^(\d+)\]:\s*(.*)$/);
    if (footnoteMatch) {
      const num = Number(footnoteMatch[1]);
      const body = footnoteMatch[2] ?? "";
      pushReferenceFootnote(num, body);
      continue;
    }

    // Footnote continuation lines (indented)
    if (lastFootnoteIndex !== null && /^\s{2,}\S+/.test(line)) {
      const extra = line.trim();
      const item = currentSection?.content[lastFootnoteIndex];
      if (item) {
        item.text = `${item.text} ${extra}`.trim();
      }
      continue;
    }

    // Bullets: - * +
    const bulletMatch = line.match(/^\s*[-*+]\s+(.*)$/);
    if (bulletMatch) {
      pushBullet(bulletMatch[1] ?? "");
      continue;
    }

    // Numbered lists: 1. item
    const numberedMatch = line.match(/^\s*\d+\.\s+(.*)$/);
    if (numberedMatch) {
      pushBullet(numberedMatch[1] ?? "");
      continue;
    }

    // Normal text line
    ensureSection("Live Report");
    paragraphBuffer.push(line.trim());
  }

  flushParagraph();
  pushSectionIfAny();

  return sections.filter((s) => s.content.length > 0);
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

function formatActionLabel(actionId: string | null) {
  if (!actionId) return "Action";
  if (actionId === "run_pipeline") return "Run research report";
  if (actionId === "quick_answer") return "Quick answer";
  return actionId.replace(/_/g, " ");
}

function displayMessageText(message: ChatMessage) {
  if (message.type === "action") {
    const actionId =
      (message.content_json?.["action_id"] as string | undefined) ??
      message.content_text.replace("__ACTION__:", "").trim();
    return formatActionLabel(actionId || null);
  }
  return message.content_text;
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
  const location = useLocation();
  const navigate = useNavigate();
  const id = projectId ?? "";
  const project = useProjectQuery(id);
  const conversations = useChatConversationsQuery(id, 200);
  const messagesQuery = useChatMessagesQuery(chatId ?? "", 200);
  const sendChat = useSendChatMessageMutation(chatId ?? "");
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null);
  const cancelRun = useCancelRunMutation(activeRun?.runId ?? "");
  const retryRun = useRetryRunMutation(activeRun?.runId ?? "");

  const [draft, setDraft] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [llmModel, setLlmModel] = useState(DEFAULT_HOSTED_MODEL);

  const [report, setReport] = useState<Report>(EMPTY_REPORT);
  const [highlightedSection, setHighlightedSection] = useState<string | null>(null);
  const [showExportModal, setShowExportModal] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);
  const [exportNotification, setExportNotification] = useState<string | null>(null);

  const lastEventIdRef = useRef<number>(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const initialMessage = useMemo(() => {
    if (!location.state || typeof location.state !== "object") return null;
    const state = location.state as { initialMessage?: string };
    return state.initialMessage ?? null;
  }, [location.state]);
  const [initialMessageSent, setInitialMessageSent] = useState(false);

  const chat = useMemo(() => {
    const items = conversations.data?.items ?? [];
    return items.find((item) => item.id === chatId) ?? null;
  }, [conversations.data, chatId]);

  const messages = messagesQuery.data?.items ?? [];

  useEffect(() => {
    if (!initialMessage || initialMessageSent || !chatId) return;
    setInitialMessageSent(true);
    void sendMessage(initialMessage).catch(() => {});
  }, [initialMessage, initialMessageSent, chatId]);

  // Scroll to bottom when messages change
  useEffect(() => {
    const node = messagesEndRef.current;
    if (node && typeof node.scrollIntoView === "function") {
      node.scrollIntoView({ behavior: "smooth" });
    }
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

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed || !chatId) return;
    setIsTyping(true);
    try {
      const response = await sendChat.mutateAsync({
        conversation_id: chatId,
        project_id: id || undefined,
        message: trimmed,
        client_message_id: generateClientMessageId(),
        llm_provider: "hosted",
        llm_model: llmModel.trim() ? llmModel.trim() : undefined
      });
      const assistant = response.assistant_message;
      if (assistant?.type === "run_started") {
        const runId = assistant.content_json?.["run_id"];
        if (typeof runId === "string") {
          setActiveRun({
            runId,
            status: "running",
            primaryText: "Starting run...",
            startedAt: new Date().toISOString()
          });
          lastEventIdRef.current = 0;
        }
      }
    } finally {
      setIsTyping(false);
    }
  }

  async function onSend() {
    const text = draft.trim();
    if (!text) return;
    try {
      await sendMessage(text);
      setDraft("");
    } catch {
      // Keep the draft so the user can retry.
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

  async function handleExport(format: string) {
    setShowExportModal(false);
    setExportNotification(`Exporting as ${format.toUpperCase()}...`);

    try {
      const filename = `${report.title || "report"}`;

      if (format === "md") {
        const content = generateMarkdown(report);
        downloadText(content, `${filename}.md`, "text/markdown");
      } else if (format === "html") {
        const content = generateHTML(report);
        downloadText(content, `${filename}.html`, "text/html");
      } else if (format === "pdf") {
        await generatePDF(report, filename);
      } else if (format === "docx") {
        await generateWord(report, filename);
      }

      setExportNotification(`Report downloaded as ${format.toUpperCase()}`);
      setTimeout(() => setExportNotification(null), 2000);
    } catch (error) {
      setExportNotification(`Export failed: ${error instanceof Error ? error.message : "Unknown error"}`);
      setTimeout(() => setExportNotification(null), 3000);
    }
  }

  function downloadText(content: string, filename: string, mimeType: string) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  async function generatePDF(report: Report, filename: string) {
    const doc = new jsPDF();
    const pageWidth = doc.internal.pageSize.getWidth();
    const pageHeight = doc.internal.pageSize.getHeight();
    const margin = 20;
    const maxWidth = pageWidth - 2 * margin;
    let yPosition = margin;

    // Title
    doc.setFontSize(20);
    doc.setFont("helvetica", "bold");
    doc.text(report.title, margin, yPosition);
    yPosition += 15;

    // Sections
    doc.setFontSize(11);
    report.sections.forEach((section) => {
      if (yPosition > pageHeight - 30) {
        doc.addPage();
        yPosition = margin;
      }

      doc.setFont("helvetica", "bold");
      doc.setFontSize(14);
      doc.text(section.heading, margin, yPosition);
      yPosition += 10;

      doc.setFont("helvetica", "normal");
      doc.setFontSize(11);

      section.content.forEach((item) => {
        let text = item.text;

        if (item.citations && item.citations.length > 0) {
          text += ` ${item.citations.map((c) => `[${c}]`).join("")}`;
        }

        if (item.isBullet) {
          text = `• ${text}`;
        }

        const lines = doc.splitTextToSize(text, maxWidth);

        const lineHeight = 7;
        const totalHeight = lines.length * lineHeight;

        if (yPosition + totalHeight > pageHeight - margin) {
          doc.addPage();
          yPosition = margin;
        }

        lines.forEach((line: string) => {
          doc.text(line, margin, yPosition);
          yPosition += lineHeight;
        });

        yPosition += 3;
      });

      yPosition += 5;
    });

    doc.save(`${filename}.pdf`);
  }

  async function generateWord(report: Report, filename: string) {
    const children: Paragraph[] = [];

    children.push(
      new Paragraph({
        text: report.title,
        heading: HeadingLevel.HEADING_1,
        spacing: { after: 200 }
      })
    );

    report.sections.forEach((section) => {
      children.push(
        new Paragraph({
          text: section.heading,
          heading: HeadingLevel.HEADING_2,
          spacing: { before: 200, after: 100 }
        })
      );

      section.content.forEach((item) => {
        const runs: TextRun[] = [new TextRun(item.text)];

        if (item.citations && item.citations.length > 0) {
          runs.push(
            new TextRun({
              text: ` ${item.citations.map((c) => `[${c}]`).join("")}`,
              superScript: true,
              color: "10b981"
            })
          );
        }

        children.push(
          new Paragraph({
            children: runs,
            bullet: item.isBullet ? { level: 0 } : undefined,
            spacing: { after: 120 }
          })
        );
      });
    });

    const doc = new Document({
      sections: [
        {
          properties: {},
          children
        }
      ]
    });

    const blob = await Packer.toBlob(doc);
    saveAs(blob, `${filename}.docx`);
  }

  function generateMarkdown(report: Report): string {
    let md = `# ${report.title}\n\n`;

    report.sections.forEach((section) => {
      md += `## ${section.heading}\n\n`;
      section.content.forEach((item) => {
        const prefix = item.isBullet ? "- " : "";
        let text = item.text;

        if (item.citations && item.citations.length > 0) {
          const citationStr = item.citations.map((c) => `[${c}]`).join("");
          text += citationStr;
        }

        md += `${prefix}${text}\n\n`;
      });
    });

    return md;
  }

  function generateHTML(report: Report): string {
    let html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${report.title}</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      max-width: 800px;
      margin: 0 auto;
      padding: 2rem;
      line-height: 1.6;
      color: #1e293b;
    }
    h1 {
      color: #0f172a;
      border-bottom: 2px solid #10b981;
      padding-bottom: 0.5rem;
    }
    h2 {
      color: #334155;
      margin-top: 2rem;
    }
    p {
      margin: 1rem 0;
    }
    ul {
      margin: 1rem 0;
    }
    li {
      margin: 0.5rem 0;
    }
    sup {
      color: #10b981;
      font-weight: 600;
    }
  </style>
</head>
<body>
  <h1>${report.title}</h1>
`;

    report.sections.forEach((section) => {
      html += `  <h2>${section.heading}</h2>\n`;

      const hasBullets = section.content.some((item) => item.isBullet);
      if (hasBullets) {
        html += "  <ul>\n";
      }

      section.content.forEach((item) => {
        let text = item.text;

        if (item.citations && item.citations.length > 0) {
          const citationStr = item.citations.map((c) => `<sup>${c}</sup>`).join("");
          text += citationStr;
        }

        if (item.isBullet) {
          html += `    <li>${text}</li>\n`;
        } else {
          if (hasBullets) {
            html += "  </ul>\n";
          }
          html += `  <p>${text}</p>\n`;
          if (hasBullets) {
            html += "  <ul>\n";
          }
        }
      });

      if (hasBullets) {
        html += "  </ul>\n";
      }
    });

    html += `</body>
</html>`;

    return html;
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
                  className={`max-w-[90%] whitespace-pre-wrap rounded-2xl px-4 py-3.5 text-sm leading-relaxed ${
                    isUser
                      ? "rounded-br-sm border border-emerald-500/30 bg-emerald-500/15 text-slate-200"
                      : isError
                        ? "rounded-bl-sm border border-rose-500/40 bg-rose-500/10 text-rose-100"
                        : "rounded-bl-sm border border-slate-700/50 bg-slate-800/80 text-slate-200"
                  }`}
                >
                  {displayMessageText(message)}
                  {isRunStarted && runId ? (
                    <div className="mt-2">
                      <Link
                        to={`/runs/${encodeURIComponent(runId)}`}
                        className="inline-flex items-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-200 hover:bg-emerald-500/20"
                      >
                        Open run viewer
                      </Link>
                    </div>
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
                        disabled={isTyping || sendChat.isPending}
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
            <span>LLM model</span>
            <input
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
              placeholder={DEFAULT_HOSTED_MODEL}
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
              placeholder="Ask a question or request a report..."
              rows={1}
              className="flex-1 resize-none rounded-xl border border-slate-700 bg-slate-800/50 px-4 py-3.5 text-sm text-slate-200 outline-none transition-colors focus:border-emerald-500/50"
            />
            <button
              onClick={() => void onSend()}
              disabled={!draft.trim() || isTyping || sendChat.isPending}
              className={`flex h-12 w-12 items-center justify-center rounded-xl transition-colors ${
                draft.trim() && !isTyping && !sendChat.isPending
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
