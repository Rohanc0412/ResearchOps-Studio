import { useMemo, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Folder, MessageSquare, Plus, Send } from "lucide-react";

import { useChatConversationsQuery, useCreateConversationMutation } from "../api/chat";
import { useProjectQuery } from "../api/projects";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";

function formatChatDate(value: string) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function GlassCard({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`relative overflow-hidden rounded-2xl border border-white/[0.09] bg-[rgba(20,20,26,0.88)] shadow-[0_8px_24px_rgba(0,0,0,0.4)] backdrop-blur-xl ${
        className ?? ""
      }`}
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-white/[0.04] to-transparent" />
      <div className="relative">{children}</div>
    </div>
  );
}

export function ProjectDetailPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const id = projectId ?? "";
  const project = useProjectQuery(id);
  const conversations = useChatConversationsQuery(id);
  const createConversation = useCreateConversationMutation();
  const [draft, setDraft] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);

  const recentChats = useMemo(() => {
    const items = conversations.data?.items ?? [];
    return items.slice(0, 10).map((chat) => ({
      id: chat.id,
      title: chat.title ?? "Untitled chat",
      ts: chat.last_message_at ?? chat.created_at
    }));
  }, [conversations.data]);

  async function createNewChat(initialMessage?: string) {
    if (!id) return;
    setCreateError(null);
    const title = initialMessage
      ? initialMessage.slice(0, 30) + (initialMessage.length > 30 ? "..." : "")
      : undefined;
    try {
      const chat = await createConversation.mutateAsync({ project_id: id, title });
      navigate(
        `/projects/${encodeURIComponent(id)}/chats/${encodeURIComponent(chat.id)}`,
        {
          state: initialMessage ? { initialMessage } : undefined
        }
      );
    } catch (e) {
      const message = e instanceof Error ? e.message : "Failed to create chat.";
      setCreateError(message);
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
    return (
      <div className="mx-auto w-full max-w-4xl">
        <GlassCard>
          <div className="p-8">
            <Spinner label="Loading project..." />
          </div>
        </GlassCard>
      </div>
    );
  }

  if (project.isError) {
    return (
      <div className="mx-auto w-full max-w-4xl">
        <ErrorBanner
          message={project.error instanceof Error ? project.error.message : "Failed to load project"}
        />
      </div>
    );
  }

  const p = project.data;
  if (!p) return null;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <Folder className="h-6 w-6 text-[#9580c4]" />
          <h1
            className="text-2xl font-bold bg-gradient-to-r from-white to-[#a5b4fc] bg-clip-text text-transparent tracking-[-0.02em]"
            style={{ fontFamily: "'Syne', sans-serif" }}
          >
            {p.name}
          </h1>
        </div>

        <button
          type="button"
          onClick={() => void createNewChat()}
          disabled={createConversation.isPending}
          className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-[#9580c4] px-5 py-3 text-sm font-semibold text-white shadow-[0_4px_12px_rgba(149,128,196,0.25)] transition-all hover:bg-[#a792ce] hover:-translate-y-px hover:shadow-[0_6px_18px_rgba(149,128,196,0.35)] active:translate-y-0 active:bg-[#8670b8] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          New chat
        </button>
      </div>

      {createError ? <ErrorBanner message={createError} /> : null}

      {/* Input area for quick start */}
      <GlassCard>
        <div className="p-6">
          <textarea
            className="w-full min-h-[80px] resize-y rounded-xl border border-white/[0.08] bg-slate-950/70 px-4 py-4 text-[15px] text-slate-100 placeholder:text-slate-500 transition focus:border-indigo-500/50 focus:outline-none focus:ring-2 focus:ring-indigo-500/10"
            placeholder={`Start a new chat in ${p.name}...`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSubmit();
              }
            }}
          />

          <div className="mt-4 flex justify-end">
            <button
              type="button"
              className="inline-flex items-center gap-2 rounded-xl bg-[#9580c4] px-5 py-3 text-sm font-semibold text-white shadow-[0_2px_8px_rgba(149,128,196,0.25)] transition hover:bg-[#a792ce] hover:shadow-[0_4px_12px_rgba(149,128,196,0.35)] disabled:cursor-not-allowed disabled:opacity-50"
              onClick={onSubmit}
              disabled={!draft.trim() || createConversation.isPending}
            >
              <Send className="h-4 w-4" />
              {createConversation.isPending ? "Starting..." : "Start chat"}
            </button>
          </div>
        </div>
      </GlassCard>

      {/* Chats list */}
      <div>
        <div className="mb-4 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Recent chats
        </div>

        {conversations.isLoading ? (
          <div className="py-10 text-center text-sm text-slate-500">Loading conversations...</div>
        ) : conversations.isError ? (
          <ErrorBanner
            message={
              conversations.error instanceof Error ? conversations.error.message : "Failed to load conversations"
            }
          />
        ) : recentChats.length > 0 ? (
          <div className="flex flex-col gap-3">
            {recentChats.map((chat) => (
              <button
                key={chat.id}
                type="button"
                className="flex w-full items-center gap-4 rounded-2xl border border-white/[0.06] bg-[rgba(20,20,26,0.88)] px-5 py-4 text-left shadow-[0_8px_24px_-4px_rgba(0,0,0,0.4)] backdrop-blur-xl transition hover:-translate-y-px hover:border-indigo-500/20 hover:bg-indigo-500/[0.08] hover:shadow-[0_4px_12px_rgba(0,0,0,0.2)]"
                onClick={() => openChat(chat.id)}
              >
                <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-indigo-500/10">
                  <MessageSquare className="h-[18px] w-[18px] text-indigo-300" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[15px] font-semibold text-slate-100">{chat.title}</div>
                </div>
                <div className="flex-shrink-0 text-xs text-slate-400">{formatChatDate(chat.ts)}</div>
              </button>
            ))}
          </div>
        ) : (
          <div className="py-10 text-center text-sm text-slate-500">
            No chats yet. Start a conversation above or click &quot;New chat&quot;.
          </div>
        )}
      </div>
    </div>
  );
}


