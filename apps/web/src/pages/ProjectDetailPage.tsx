import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Folder, MessageSquare, Plus } from "lucide-react";

import { useProjectQuery } from "../api/projects";
import { Card } from "../components/ui/Card";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";
import { Textarea } from "../components/ui/Textarea";
import { formatTs } from "../utils/format";

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

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function ProjectDetailPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const id = projectId ?? "";
  const project = useProjectQuery(id);

  const storageKey = useMemo(() => (id ? `researchops.chats.${id}` : ""), [id]);
  const [chats, setChats] = useState<Chat[]>(() => {
    // Initialize from localStorage synchronously
    if (!id) return [];
    const key = `researchops.chats.${id}`;
    const raw = window.localStorage.getItem(key);
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw) as Chat[];
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  });
  const [draft, setDraft] = useState("");

  // Reload chats when project changes
  useEffect(() => {
    if (!storageKey) return;
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      setChats([]);
      return;
    }
    try {
      const parsed = JSON.parse(raw) as Chat[];
      setChats(Array.isArray(parsed) ? parsed : []);
    } catch {
      setChats([]);
    }
  }, [storageKey]);

  // Save chats to localStorage (only when chats actually change, not on initial load)
  const isInitialMount = useRef(true);
  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }
    if (!storageKey) return;
    window.localStorage.setItem(storageKey, JSON.stringify(chats));
  }, [storageKey, chats]);

  const recentChats = useMemo(() => {
    return chats
      .map((chat) => {
        const last = chat.messages[chat.messages.length - 1];
        return {
          id: chat.id,
          title: chat.title,
          preview: last ? last.content.slice(0, 60) : "",
          ts: last ? last.ts : chat.createdAt
        };
      })
      .slice(0, 10);
  }, [chats]);

  function createNewChat(initialMessage?: string) {
    const now = new Date().toISOString();
    const chatId = generateId();
    const chat: Chat = {
      id: chatId,
      title: initialMessage ? initialMessage.slice(0, 30) + (initialMessage.length > 30 ? "..." : "") : `Chat ${chats.length + 1}`,
      createdAt: now,
      messages: initialMessage
        ? [
            {
              id: generateId(),
              role: "user" as const,
              content: initialMessage,
              ts: now
            }
          ]
        : []
    };
    const updatedChats = [chat, ...chats];
    setChats(updatedChats);
    // Save immediately to localStorage before navigating
    window.localStorage.setItem(storageKey, JSON.stringify(updatedChats));
    // Notify sidebar of chat update
    window.dispatchEvent(new Event("researchops-chats-updated"));
    // Navigate to the new chat
    navigate(`/projects/${id}/chats/${chatId}${initialMessage ? "?autorun=true" : ""}`);
  }

  function openChat(chatId: string) {
    navigate(`/projects/${id}/chats/${chatId}`);
  }

  function onSubmit() {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    createNewChat(text);
  }

  if (project.isLoading) {
    return (
      <Card>
        <Spinner label="Loading project..." />
      </Card>
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
    <div className="flex flex-col gap-6">
      <div className="mx-auto flex w-full max-w-3xl items-center justify-between">
        <div className="flex items-center gap-2 text-slate-100">
          <Folder className="h-5 w-5 text-slate-300" />
          <div className="text-lg font-semibold">{p.name}</div>
        </div>
        <button
          type="button"
          onClick={() => createNewChat()}
          className="flex items-center gap-1.5 rounded-md bg-slate-800 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-700"
        >
          <Plus className="h-4 w-4" />
          New chat
        </button>
      </div>

      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
        {/* Input area for quick start */}
        <div className="rounded-2xl bg-slate-800/60 p-4">
          <Textarea
            rows={2}
            className="border-0 bg-transparent text-slate-100 placeholder-slate-500 focus:border-transparent focus:ring-0"
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
          <div className="mt-3 flex items-center justify-end">
            <button
              type="button"
              className="flex items-center gap-2 rounded-md bg-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-600 disabled:opacity-50"
              onClick={onSubmit}
              disabled={!draft.trim()}
            >
              Start chat
            </button>
          </div>
        </div>

        {/* Chats list */}
        {recentChats.length > 0 && (
          <div>
            <div className="mb-3 text-xs font-medium uppercase text-slate-500">Recent chats</div>
            <div className="flex flex-col gap-2">
              {recentChats.map((chat) => (
                <button
                  key={chat.id}
                  type="button"
                  className="flex items-center gap-3 rounded-xl bg-slate-900/50 px-4 py-3 text-left hover:bg-slate-800/50"
                  onClick={() => openChat(chat.id)}
                >
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-800">
                    <MessageSquare className="h-4 w-4 text-slate-400" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-slate-200">{chat.title}</div>
                    {chat.preview && (
                      <div className="truncate text-sm text-slate-500">{chat.preview}</div>
                    )}
                  </div>
                  <div className="text-xs text-slate-500">{formatTs(chat.ts)}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {recentChats.length === 0 && (
          <div className="py-8 text-center text-slate-500">
            No chats yet. Start a conversation above or click "New chat".
          </div>
        )}
      </div>
    </div>
  );
}
