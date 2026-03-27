import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ChevronRight, Folder, MessageSquare, Plus, Send } from "lucide-react";

import { useChatConversationsQuery, useCreateConversationMutation } from "../api/chat";
import { useProjectQuery } from "../api/projects";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";

function formatChatDate(value: string) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
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
      ts: chat.last_message_at ?? chat.created_at,
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
        { state: initialMessage ? { initialMessage } : undefined }
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
      <div className="flex justify-center py-16">
        <Spinner label="Loading project…" />
      </div>
    );
  }

  if (project.isError) {
    return (
      <ErrorBanner
        message={project.error instanceof Error ? project.error.message : "Failed to load project"}
      />
    );
  }

  const p = project.data;
  if (!p) return null;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8">
      {/* Page header */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-obsidian-accent-dim">
            <Folder className="h-4 w-4 text-obsidian-accent" />
          </div>
          <h1 className="font-display text-2xl font-semibold text-obsidian-text">
            {p.name}
          </h1>
        </div>
        <Button
          onClick={() => void createNewChat()}
          loading={createConversation.isPending}
          className="shrink-0"
        >
          <Plus className="h-4 w-4" />
          New chat
        </Button>
      </div>

      {createError && <ErrorBanner message={createError} />}

      {/* Prompt box */}
      <div className="overflow-hidden rounded-xl border border-obsidian-border bg-obsidian-surface-elevated">
        <textarea
          className="w-full resize-none bg-transparent px-5 pt-5 pb-3 text-sm font-sans text-obsidian-text placeholder:text-obsidian-muted focus:outline-none"
          rows={4}
          placeholder="Ask a research question…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit();
            }
          }}
        />
        <div className="flex items-center justify-between border-t border-obsidian-border-subtle px-4 py-3">
          <span className="text-xs text-obsidian-muted">
            Press{" "}
            <kbd className="rounded border border-obsidian-border px-1 py-0.5 font-mono text-[10px]">
              Enter
            </kbd>{" "}
            to send,{" "}
            <kbd className="rounded border border-obsidian-border px-1 py-0.5 font-mono text-[10px]">
              Shift+Enter
            </kbd>{" "}
            for newline
          </span>
          <Button
            size="sm"
            onClick={onSubmit}
            disabled={!draft.trim()}
            loading={createConversation.isPending}
          >
            <Send className="h-3.5 w-3.5" />
            {createConversation.isPending ? "Starting…" : "Start chat"}
          </Button>
        </div>
      </div>

      {/* Recent sessions */}
      <div className="flex flex-col gap-3">
        <div className="text-[11px] font-semibold uppercase tracking-widest text-obsidian-muted">
          Recent Sessions
        </div>

        {conversations.isLoading ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : conversations.isError ? (
          <ErrorBanner
            message={
              conversations.error instanceof Error
                ? conversations.error.message
                : "Failed to load conversations"
            }
          />
        ) : recentChats.length > 0 ? (
          <div className="overflow-hidden rounded-xl border border-obsidian-border">
            {recentChats.map((chat, i) => (
              <button
                key={chat.id}
                type="button"
                onClick={() => openChat(chat.id)}
                className={[
                  "flex w-full cursor-pointer items-center gap-4 px-5 py-4 text-left",
                  "bg-obsidian-surface-elevated transition-colors hover:bg-obsidian-accent-dim",
                  i < recentChats.length - 1 ? "border-b border-obsidian-border-subtle" : "",
                ].join(" ")}
              >
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-obsidian-accent-dim">
                  <MessageSquare className="h-3.5 w-3.5 text-obsidian-accent" />
                </div>
                <span className="flex-1 truncate text-sm font-medium text-obsidian-text">
                  {chat.title}
                </span>
                <span className="shrink-0 font-mono text-xs text-obsidian-muted">
                  {formatChatDate(chat.ts)}
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-obsidian-muted" />
              </button>
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
