import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, SendHorizontal } from "lucide-react";

import { useProjectQuery } from "../api/projects";
import { useCreateRunMutation, useCancelRunMutation, useRetryRunMutation } from "../api/runs";
import { apiFetchJson } from "../api/client";
import { Card } from "../components/ui/Card";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";
import { Textarea } from "../components/ui/Textarea";
import { formatTs } from "../utils/format";
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

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function titleCase(value: string): string {
  if (!value) return value;
  return value.replace(/(^|_|-)([a-z])/g, (_, sep, ch) => `${sep} ${ch.toUpperCase()}`).trim();
}

function buildFinalResponse(artifacts: Artifact[]): string {
  for (const artifact of artifacts) {
    const md = artifact.metadata?.markdown;
    if (typeof md === "string" && md.trim()) return md.trim();
    const msg = artifact.metadata?.message;
    if (typeof msg === "string" && msg.trim()) return msg.trim();
  }
  return "Run completed. Output is available in artifacts.";
}

function deriveRunUpdate(event: { stage?: string; message?: string; payload?: Record<string, unknown> }) {
  const payload = event.payload ?? {};
  const rawStatus = payload.status ?? payload.to_status;
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

  if (typeof payload.step === "string" && payload.step.trim()) {
    secondaryText = `Step: ${payload.step}`;
  } else if (typeof payload.artifact_type === "string" && payload.artifact_type.trim()) {
    secondaryText = `Artifact: ${payload.artifact_type}`;
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

  const [runArtifacts, setRunArtifacts] = useState<Record<string, Artifact[]>>({});
  const [lastCompletedRunId, setLastCompletedRunId] = useState<string | null>(null);

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

  // Handle autorun parameter - automatically start a run if coming from quick-start
  useEffect(() => {
    if (autorunHandled) return;
    if (!chat || !id || activeRun) return;
    const autorun = searchParams.get("autorun");
    if (autorun !== "true") return;

    // Find the first user message to use as prompt
    const firstUserMsg = messages.find((m) => m.role === "user");
    if (!firstUserMsg) return;

    setAutorunHandled(true);
    // Clear the autorun param from URL
    setSearchParams({}, { replace: true });

    // Start the run
    void (async () => {
      try {
        const run = await createRun.mutateAsync({ prompt: firstUserMsg.content });
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
      }
    })();
  }, [chat, id, messages, activeRun, autorunHandled, searchParams, setSearchParams, createRun]);

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
      if (artifacts.length > 0) {
        setRunArtifacts((prev) => ({ ...prev, [runId]: artifacts }));
      }
      setLastCompletedRunId(runId);
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

    if (!id) return;

    try {
      const run = await createRun.mutateAsync({ prompt: text });
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
        prev
          ? { ...prev, status: "running", primaryText: "Retrying run", secondaryText: undefined }
          : prev
      );
    } catch {
      // no-op
    }
  }

  if (project.isLoading) {
    return (
      <Card>
        <Spinner label="Loading..." />
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

  if (!chat) {
    return (
      <Card>
        <div className="text-slate-400">Chat not found</div>
      </Card>
    );
  }

  const artifactsForLastRun = lastCompletedRunId ? runArtifacts[lastCompletedRunId] : null;

  return (
    <div className="flex h-full flex-col">
      {/* Header with back button */}
      <div className="border-b border-slate-800 px-4 py-3">
        <div className="mx-auto flex max-w-3xl items-center gap-3">
          <button
            type="button"
            onClick={() => navigate(`/projects/${id}`)}
            className="flex h-8 w-8 items-center justify-center rounded-md text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
          <div>
            <div className="font-medium text-slate-100">{chat.title}</div>
            <div className="text-xs text-slate-500">{p.name}</div>
          </div>
        </div>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto max-w-3xl">
          {messages.length === 0 ? (
            <div className="py-12 text-center text-slate-500">
              Start a conversation by sending a message below.
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              {messages.map((m) => (
                <div
                  key={m.id}
                  className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                      m.role === "user"
                        ? "bg-slate-700 text-slate-100"
                        : "bg-slate-900 text-slate-200"
                    }`}
                  >
                    <div className="whitespace-pre-wrap text-sm">{m.content}</div>
                    <div className="mt-2 text-xs text-slate-500">{formatTs(m.ts)}</div>
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}

          {/* Run status banner */}
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

          {/* Artifacts */}
          {artifactsForLastRun && artifactsForLastRun.length > 0 && (
            <div className="mt-4">
              <Card>
                <details>
                  <summary className="cursor-pointer text-sm font-semibold text-slate-100">
                    Artifacts
                  </summary>
                  <div className="mt-3 space-y-3 text-xs text-slate-300">
                    {artifactsForLastRun.map((artifact) => (
                      <div key={artifact.id} className="rounded-md border border-slate-900 bg-black/20 p-3">
                        <div className="text-slate-100">{artifact.type}</div>
                        <pre className="mt-2 whitespace-pre-wrap">{JSON.stringify(artifact.metadata ?? {}, null, 2)}</pre>
                      </div>
                    ))}
                  </div>
                </details>
              </Card>
            </div>
          )}
        </div>
      </div>

      {/* Input area fixed at bottom */}
      <div className="border-t border-slate-800 px-4 py-4">
        <div className="mx-auto max-w-3xl">
          <div className="flex items-end gap-3">
            <Textarea
              rows={1}
              className="flex-1 resize-none rounded-xl border-slate-700 bg-slate-800 text-slate-100 placeholder-slate-500"
              placeholder="Type a message..."
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void onSend();
                }
              }}
            />
            <button
              type="button"
              className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-700 text-slate-200 hover:bg-slate-600 disabled:opacity-50"
              onClick={() => void onSend()}
              disabled={createRun.isPending || !draft.trim()}
            >
              <SendHorizontal className="h-5 w-5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
