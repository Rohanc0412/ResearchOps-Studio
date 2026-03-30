import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ChevronRight, FlaskConical, MessageSquare, Plus, Send } from "lucide-react";

import { useChatConversationsQuery, useCreateConversationMutation } from "../api/chat";
import { ApiError } from "../api/client";
import { useProjectQuery } from "../api/projects";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";

// All solid hex — no rgba, no opacity modifiers
const BG      = "#0b0b0e";
const SURFACE = "#101015";
const BORDER  = "#1c1c24";
const ACCENT  = "#9580c4";
const TEXT    = "#e0dde6";
const MUTED   = "#8a8694";

const CARD_STYLE = { backgroundColor: BG,      boxShadow: `0 0 0 1px ${BORDER}` } as const;
const CARD_HOVER = { backgroundColor: SURFACE,  boxShadow: `0 0 0 1px ${BORDER}` } as const;

function formatChatDate(value: string) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function ProjectDetailPage() {
  const { projectId } = useParams();
  const navigate      = useNavigate();
  const id            = projectId ?? "";
  const project       = useProjectQuery(id);
  const conversations = useChatConversationsQuery(id);
  const createConv    = useCreateConversationMutation();

  const [draft, setDraft]           = useState("");
  const [runPipeline, setRunPipeline] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const recentChats = useMemo(() => {
    const items = conversations.data?.items ?? [];
    return items.slice(0, 10).map((chat) => ({
      id:    chat.id,
      title: chat.title ?? "Untitled chat",
      ts:    chat.last_message_at ?? chat.created_at,
    }));
  }, [conversations.data]);

  async function createNewChat(initialMessage?: string) {
    if (!id) return;
    setCreateError(null);
    const title = initialMessage
      ? initialMessage.slice(0, 30) + (initialMessage.length > 30 ? "..." : "")
      : undefined;
    try {
      const chat = await createConv.mutateAsync({ project_id: id, title });
      navigate(
        `/projects/${encodeURIComponent(id)}/chats/${encodeURIComponent(chat.id)}`,
        { state: initialMessage || runPipeline ? { initialMessage, runPipeline } : undefined },
      );
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : "Failed to create chat.");
    }
  }

  function openChat(chatId: string) {
    navigate(`/projects/${encodeURIComponent(id)}/chats/${encodeURIComponent(chatId)}`);
  }

  function onSubmit() {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    void createNewChat(text);
  }

  if (project.isLoading) {
    return <div className="flex justify-center py-16"><Spinner label="Loading project..." /></div>;
  }
  if (project.isError) {
    if (project.error instanceof ApiError && project.error.status === 404) {
      return (
        <EmptyState
          icon={<FlaskConical size={32} />}
          title="Project not found"
          description="This project doesn't exist or you don't have access to it."
          action={<Button onClick={() => navigate("/projects")}>Go to Projects</Button>}
        />
      );
    }
    return <ErrorBanner message={project.error instanceof Error ? project.error.message : "Failed to load project"} />;
  }
  const p = project.data;
  if (!p) return null;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-4">
        <h1 className="font-display text-2xl font-semibold" style={{ color: TEXT }}>
          {p.name}
        </h1>
        <Button onClick={() => void createNewChat()} loading={createConv.isPending} className="shrink-0">
          <Plus className="h-4 w-4" />
          New chat
        </Button>
      </div>

      {createError && <ErrorBanner message={createError} />}

      {/* ── Prompt box ──────────────────────────────────────────────────────── */}
      {/*
        Strategy: the outer shell is a transparent wrapper that only draws a
        border via box-shadow. The textarea and toolbar are siblings, each with
        backgroundColor = BG (page color). A real <div> separator (height 1px,
        solid color) sits between them. Zero rgba, zero nested backgrounds.
      */}
      <div className="overflow-hidden rounded-xl" style={{ boxShadow: `0 0 0 1px ${BORDER}` }}>
        {/* Textarea — its own element, background = page bg */}
        <textarea
          className="w-full resize-none px-5 pt-5 pb-3 text-sm font-sans focus:outline-none"
          style={{ backgroundColor: BG, color: TEXT, caretColor: ACCENT, display: "block" }}
          rows={4}
          placeholder={
            runPipeline
              ? "Describe your research topic - a full report will run automatically..."
              : "Ask a research question..."
          }
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSubmit(); }
          }}
        />

        {/* Separator — a real div, not a CSS border, avoids compositing */}
        <div style={{ height: 1, backgroundColor: BORDER }} />

        {/* Toolbar — its own element, background = page bg */}
        <div
          className="flex items-center justify-between gap-3 px-4 py-3"
          style={{ backgroundColor: BG }}
        >
          <div className="flex items-center gap-3 min-w-0">
            <span className="hidden shrink-0 text-xs sm:block" style={{ color: MUTED }}>
              Press{" "}
              <kbd className="rounded px-1 py-0.5 font-mono text-[10px]"
                style={{ border: `1px solid ${BORDER}`, color: MUTED, backgroundColor: SURFACE }}>
                Enter
              </kbd>{" "}
              to send,{" "}
              <kbd className="rounded px-1 py-0.5 font-mono text-[10px]"
                style={{ border: `1px solid ${BORDER}`, color: MUTED, backgroundColor: SURFACE }}>
                Shift+Enter
              </kbd>{" "}
              for newline
            </span>

            {/* Pipeline toggle — inline style, solid color only */}
            <button
              type="button"
              aria-pressed={runPipeline}
              onClick={() => setRunPipeline((v) => !v)}
              className="flex shrink-0 cursor-pointer items-center gap-1.5 rounded-full px-3 py-1.5 text-xs"
              style={
                runPipeline
                  ? { backgroundColor: ACCENT, color: "#fff", border: `1px solid ${ACCENT}` }
                  : { backgroundColor: SURFACE, color: MUTED, border: `1px solid ${BORDER}` }
              }
            >
              <FlaskConical className="h-3 w-3" />
              Run research report
            </button>
          </div>

          <Button size="sm" onClick={onSubmit} disabled={!draft.trim()} loading={createConv.isPending}>
            <Send className="h-3.5 w-3.5" />
            {createConv.isPending ? "Starting…" : "Start chat"}
          </Button>
        </div>
      </div>

      {/* ── Recent sessions ─────────────────────────────────────────────────── */}
      <div className="flex flex-col gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>
          Recent Sessions
        </p>

        {conversations.isLoading ? (
          <div className="flex justify-center py-10"><Spinner /></div>
        ) : conversations.isError ? (
          <ErrorBanner
            message={conversations.error instanceof Error ? conversations.error.message : "Failed to load conversations"}
          />
        ) : recentChats.length > 0 ? (
          <div className="flex flex-col gap-2">
            {recentChats.map((chat) => (
              /* Each row = one element, background = page bg, border via box-shadow */
              <div
                key={chat.id}
                role="button"
                tabIndex={0}
                onClick={() => openChat(chat.id)}
                onKeyDown={(e) => e.key === "Enter" && openChat(chat.id)}
                className="flex cursor-pointer items-center gap-4 rounded-xl px-5 py-4"
                style={CARD_STYLE}
                onMouseEnter={(e) => Object.assign((e.currentTarget as HTMLElement).style, CARD_HOVER)}
                onMouseLeave={(e) => Object.assign((e.currentTarget as HTMLElement).style, CARD_STYLE)}
              >
                <MessageSquare className="h-4 w-4 shrink-0" style={{ color: ACCENT }} />
                <span className="flex-1 truncate text-sm font-medium" style={{ color: TEXT }}>
                  {chat.title}
                </span>
                <span className="shrink-0 font-mono text-xs" style={{ color: MUTED }}>
                  {formatChatDate(chat.ts)}
                </span>
                <ChevronRight className="h-4 w-4 shrink-0" style={{ color: MUTED }} />
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<MessageSquare className="h-5 w-5" />}
            title="No sessions yet"
            description="Ask a research question above to start your first chat."
          />
        )}
      </div>
    </div>
  );
}
