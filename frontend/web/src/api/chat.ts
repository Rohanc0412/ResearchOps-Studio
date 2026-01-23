/**
 * frontend/web/src/api/chat.ts
 *
 * High-level purpose (non technical explanation):
 * This file is the “chat data manager” for your app.
 * It is responsible for:
 * 1) Loading chat conversations (chat list)
 * 2) Loading chat messages (inside a conversation)
 * 3) Sending a message (and showing it instantly in the UI)
 * 4) Handling assistant streaming (assistant message appears gradually)
 *
 * Technical explanation:
 * - Uses TanStack React Query to fetch + cache server data
 * - Uses useInfiniteQuery for pagination (loads messages page-by-page)
 * - Uses useMutation for “write” operations (create conversation, send message)
 * - Uses Zod schemas to validate backend responses (prevents silent bugs)
 *
 * Why this matters:
 * - Fast UI: message appears instantly (optimistic UI)
 * - Scales: chats can have thousands of messages (infinite pagination)
 * - Smooth assistant UX: assistant reply streams in chunks (SSE/WS streaming)
 */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData
} from "@tanstack/react-query";
import { z } from "zod";

import { apiFetchJson } from "./client";
import { ChatConversationSchema, ChatMessageSchema, type ChatMessage } from "../types/dto";

/* ============================================================================
 * 1) ZOD SCHEMAS (Runtime validation for server responses)
 * ============================================================================
 *
 * Non technical explanation:
 * The server sends JSON responses.
 * These schemas act like a “shape checker” to confirm the data looks correct.
 *
 * Technical explanation:
 * Zod validates response structure at runtime, and gives typed inference in TS.
 */

const ConversationListSchema = z
  .object({
    // items = array of conversations
    items: z.array(ChatConversationSchema),

    // next_cursor = pagination token for future expansion (optional)
    next_cursor: z.string().nullable().optional()
  })
  .passthrough();

const MessagePageSchema = z
  .object({
    // items = messages in this page
    items: z.array(ChatMessageSchema),

    // next_cursor = token used to fetch the next page (older messages)
    next_cursor: z.string().nullable().optional()
  })
  .passthrough();

const SendResponseSchema = z
  .object({
    // conversation_id = which chat thread this belongs to
    conversation_id: z.string().min(1),

    // user_message = server-confirmed user message saved in DB
    user_message: ChatMessageSchema,

    /**
     * assistant_message can be:
     * - present (if backend returns assistant reply immediately)
     * - null / missing (if reply will be streamed later)
     */
    assistant_message: ChatMessageSchema.nullable().optional(),

    /**
     * pending_action is optional metadata for future use:
     * example: “assistant needs tool call” or “run continuation”
     */
    pending_action: z.record(z.unknown()).nullable().optional(),

    /**
     * idempotent_replay helps dedupe retries:
     * if user accidentally sends the same request again,
     * backend can replay the previous result.
     */
    idempotent_replay: z.boolean().optional()
  })
  .passthrough();

type SendResponse = z.infer<typeof SendResponseSchema>;
type MessagePage = z.infer<typeof MessagePageSchema>;

/* ============================================================================
 * 2) REACT QUERY KEYS (Cache identifiers)
 * ============================================================================
 *
 * Non technical explanation:
 * React Query stores data in its cache using “keys”.
 * Keys are like labels on folders in a filing cabinet.
 *
 * Technical explanation:
 * The same key always refers to the same cached dataset.
 * If you change the key structure, invalidation and updates can break.
 */

const chatConversationsKey = (projectId: string, limit: number) =>
  ["chat-conversations", projectId, limit] as const;

const chatMessagesKey = (conversationId: string, limit: number) =>
  ["chat-messages", conversationId, limit] as const;

const chatMessagesInfiniteKey = (conversationId: string, pageSize: number) =>
  ["chat-messages-infinite", conversationId, pageSize] as const;

/* ============================================================================
 * 3) MERGE + SORT HELPERS (Keep message list clean and ordered)
 * ============================================================================
 *
 * Non technical explanation:
 * Sometimes you can receive the same message twice:
 * - optimistic message from client
 * - real message from server
 * Or messages may come out of order when streaming.
 *
 * This helper merges them safely and keeps them ordered by time.
 *
 * Technical explanation:
 * Dedup by message.id via Map, then stable sort by created_at.
 */

function mergeChatMessages(existing: ChatMessage[], additions: ChatMessage[]) {
  const merged = new Map<string, ChatMessage>();

  // Put existing messages in first
  for (const item of existing) merged.set(item.id, item);

  // Add new messages, overwriting duplicates by id
  for (const item of additions) merged.set(item.id, item);

  // Convert Map -> array and sort
  const items = Array.from(merged.values());
  items.sort((a, b) => {
    const byTime = a.created_at.localeCompare(b.created_at);
    return byTime !== 0 ? byTime : a.id.localeCompare(b.id);
  });

  return items;
}

/**
 * Infinite Query data is stored like this:
 *
 * {
 *   pages: [page0, page1, page2, ...],
 *   pageParams: [...]
 * }
 *
 * If there is no cache yet, we create a safe empty version.
 */
function ensureInfiniteShape(page: MessagePage | undefined): InfiniteData<MessagePage> {
  return {
    pages: [page ?? { items: [], next_cursor: null }],
    pageParams: [undefined]
  };
}

/**
 * flattenInfiniteMessages()
 *
 * Non technical explanation:
 * Infinite pagination loads messages in “chunks” (pages).
 * But the UI wants one simple list of messages to render.
 *
 * Technical explanation:
 * Page 0 is newest messages.
 * Next pages are older messages.
 * To show messages from oldest to newest, we reverse the pages.
 */
export function flattenInfiniteMessages(data?: InfiniteData<MessagePage>): ChatMessage[] {
  if (!data) return [];
  return [...data.pages].reverse().flatMap((p) => p.items);
}

/* ============================================================================
 * 4) CACHE UPDATE TOOLS FOR PAGINATED DATA
 * ============================================================================
 *
 * Non technical explanation:
 * Because messages are split across pages, updating the cache is harder.
 * We need helper functions that can:
 * - insert a message
 * - update a message
 * - remove a message
 * across any page where it might exist.
 *
 * Technical explanation:
 * These helpers manipulate InfiniteData<MessagePage> safely.
 */

/**
 * upsertMessageInInfinite()
 *
 * Upsert means:
 * - If message exists, update it
 * - If message does not exist, insert it
 *
 * We use upsert for:
 * - optimistic UI insertion
 * - streaming delta updates
 * - patching messages after server response
 */
function upsertMessageInInfinite(
  data: InfiniteData<MessagePage>,
  message: ChatMessage,
  opts?: { preferNewestPage?: boolean }
): InfiniteData<MessagePage> {
  const preferNewestPage = opts?.preferNewestPage ?? true;

  // Try to find the message and update it
  let found = false;

  const updatedPages = data.pages.map((p) => {
    const idx = p.items.findIndex((m) => m.id === message.id);
    if (idx === -1) return p;

    found = true;

    // Create a new array and replace the message
    const nextItems = [...p.items];
    nextItems[idx] = { ...nextItems[idx], ...message };

    // Ensure messages remain sorted inside that page
    return { ...p, items: mergeChatMessages(nextItems, []) };
  });

  // If updated, return new cache
  if (found) {
    return { ...data, pages: updatedPages };
  }

  // Not found, insert into newest page by default
  const targetIndex = preferNewestPage ? 0 : updatedPages.length - 1;
  const targetPage = updatedPages[targetIndex] ?? { items: [], next_cursor: null };

  const nextTargetPage: MessagePage = {
    ...targetPage,
    items: mergeChatMessages(targetPage.items, [message])
  };

  const nextPages = [...updatedPages];
  nextPages[targetIndex] = nextTargetPage;

  return { ...data, pages: nextPages };
}

/**
 * removeMessageFromInfinite()
 *
 * Non technical explanation:
 * If sending fails, we remove the optimistic message bubble from UI.
 *
 * Technical explanation:
 * Filter out a message id across every page.
 */
function removeMessageFromInfinite(data: InfiniteData<MessagePage>, id: string): InfiniteData<MessagePage> {
  return {
    ...data,
    pages: data.pages.map((p) => ({
      ...p,
      items: p.items.filter((m) => m.id !== id)
    }))
  };
}

/**
 * replaceMessageIdInInfinite()
 *
 * Non technical explanation:
 * When user hits “Send”, we create a fake message id locally so UI updates instantly.
 * Later, server returns the real saved message with a real id.
 * This function swaps the fake one with the real one.
 *
 * Technical explanation:
 * Replace message with id=fromId by the toMessage.
 * If not found, upsert toMessage as fallback.
 */
function replaceMessageIdInInfinite(
  data: InfiniteData<MessagePage>,
  fromId: string,
  toMessage: ChatMessage
): InfiniteData<MessagePage> {
  let replaced = false;

  const pages = data.pages.map((p) => {
    const nextItems = p.items.map((m) => {
      if (m.id !== fromId) return m;
      replaced = true;
      return toMessage;
    });

    return { ...p, items: mergeChatMessages(nextItems, []) };
  });

  if (replaced) return { ...data, pages };

  // If we didn't find the optimistic message, insert server message anyway
  return upsertMessageInInfinite({ ...data, pages }, toMessage, { preferNewestPage: true });
}

/* ============================================================================
 * 5) READ OPERATIONS (Queries)
 * ============================================================================
 *
 * Non technical explanation:
 * Queries are “read operations”.
 * They load data from backend and keep it in cache.
 *
 * Technical explanation:
 * useQuery for simple lists.
 * useInfiniteQuery for paginated message history.
 */

/**
 * useChatConversationsQuery()
 *
 * Loads conversation list for a project.
 * Equivalent to “chat sidebar list”.
 */
export function useChatConversationsQuery(projectId: string, limit = 50) {
  return useQuery({
    queryKey: chatConversationsKey(projectId, limit),
    queryFn: async () =>
      apiFetchJson(`/chat/conversations?project_id=${encodeURIComponent(projectId)}&limit=${limit}`, {
        schema: ConversationListSchema
      }),

    // do not run until projectId exists
    enabled: Boolean(projectId)
  });
}

/**
 * useChatMessagesQuery()
 *
 * Loads the latest messages as a single page.
 */
export function useChatMessagesQuery(conversationId: string, limit = 200) {
  return useQuery({
    queryKey: chatMessagesKey(conversationId, limit),
    queryFn: async () =>
      apiFetchJson(`/chat/conversations/${encodeURIComponent(conversationId)}/messages?limit=${limit}`, {
        schema: MessagePageSchema
      }),
    enabled: Boolean(conversationId)
  });
}

/**
 * useChatMessagesInfiniteQuery()
 *
 * Loads messages page-by-page using cursor pagination.
 *
 * Non technical explanation:
 * This prevents loading thousands of messages at once.
 * The UI can load more when user scrolls up.
 *
 * Technical explanation:
 * - pageParam = cursor token
 * - backend returns next_cursor for older page
 */
export function useChatMessagesInfiniteQuery(conversationId: string, pageSize = 50) {
  return useInfiniteQuery({
    queryKey: chatMessagesInfiniteKey(conversationId, pageSize),
    enabled: Boolean(conversationId),

    // first request has no cursor
    initialPageParam: undefined as string | undefined,

    queryFn: async ({ pageParam }) => {
      const cursorPart = pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : "";
      return apiFetchJson(
        `/chat/conversations/${encodeURIComponent(conversationId)}/messages?limit=${pageSize}${cursorPart}`,
        { schema: MessagePageSchema }
      );
    },

    // React Query will use this to fetch older pages
    getNextPageParam: (lastPage) => lastPage?.next_cursor ?? undefined
  });
}

/* ============================================================================
 * 6) WRITE OPERATIONS (Mutations)
 * ============================================================================
 *
 * Non technical explanation:
 * Mutations are “write operations”.
 * They change server state, then we update UI cache.
 *
 * Technical explanation:
 * useMutation runs POST requests and allows optimistic updates.
 */

/**
 * useCreateConversationMutation()
 *
 * Creates a new conversation.
 * After success, it refreshes the conversation list in the UI.
 */
export function useCreateConversationMutation() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async (input: { project_id?: string; title?: string | null }) =>
      apiFetchJson("/chat/conversations", {
        method: "POST",
        body: input,
        schema: ChatConversationSchema
      }),

    onSuccess: async (_conversation, input) => {
      // Mark conversation list as stale so it refetches
      if (input.project_id) {
        await qc.invalidateQueries({ queryKey: ["chat-conversations", input.project_id] });
      } else {
        await qc.invalidateQueries({ queryKey: ["chat-conversations"] });
      }
    }
  });
}

export function useSendChatMessageMutation(conversationId: string, limit = 200) {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async (input: {
      conversation_id: string;
      project_id?: string;
      message: string;
      client_message_id: string;
      llm_provider?: "hosted";
      llm_model?: string;
      force_pipeline?: boolean;
    }) =>
      apiFetchJson("/chat/send", {
        method: "POST",
        body: input,
        schema: SendResponseSchema
      }),
    onMutate: async (input) => {
      if (!conversationId) return undefined;

      const key = chatMessagesKey(conversationId, limit);
      await qc.cancelQueries({ queryKey: key });

      const previous = qc.getQueryData<MessagePage>(key);
      const optimisticId = `client:${input.client_message_id}`;
      const isAction = input.message.startsWith("__ACTION__:");
      const optimisticMessage: ChatMessage = {
        id: optimisticId,
        role: "user",
        type: isAction ? "action" : "chat",
        content_text: input.message,
        content_json: null,
        created_at: new Date().toISOString(),
        client_message_id: input.client_message_id,
        optimistic: true
      };

      qc.setQueryData<MessagePage | undefined>(key, (prev) => {
        const existing = prev?.items ?? [];
        return {
          items: mergeChatMessages(existing, [optimisticMessage]),
          next_cursor: prev?.next_cursor ?? null
        };
      });

      return { previous, optimisticId };
    },
    onError: (_error, _input, context) => {
      if (!conversationId) return;
      const key = chatMessagesKey(conversationId, limit);
      if (context?.previous) {
        qc.setQueryData(key, context.previous);
        return;
      }
      if (context?.optimisticId) {
        qc.setQueryData<MessagePage | undefined>(key, (prev) => {
          if (!prev) return prev;
          return {
            items: prev.items.filter((item) => item.id !== context.optimisticId),
            next_cursor: prev.next_cursor ?? null
          };
        });
      }
    },
    onSuccess: (data: SendResponse, _input, context) => {
      if (conversationId) {
        const key = chatMessagesKey(conversationId, limit);
        qc.setQueryData<MessagePage | undefined>(key, (prev) => {
          const existing = prev?.items ?? [];
          const withoutOptimistic = context?.optimisticId
            ? existing.filter((item) => item.id !== context.optimisticId)
            : existing;
          const additions = [data.user_message, data.assistant_message].filter(
            (item): item is ChatMessage => Boolean(item)
          );
          return {
            items: mergeChatMessages(withoutOptimistic, additions),
            next_cursor: prev?.next_cursor ?? null
          };
        });
      }
      void qc.invalidateQueries({ queryKey: ["chat-conversations"] });
    }
  });
}

/* ============================================================================
 * 7) STREAMING SUPPORT (Assistant message grows gradually)
 * ============================================================================
 *
 * Non technical explanation:
 * The assistant reply can arrive in small pieces.
 * Like typing: the text appears gradually instead of all at once.
 *
 * Technical explanation:
 * This is typically driven by SSE or WebSocket events containing:
 * - delta chunks (partial text)
 * - final completion event
 *
 * These functions update React Query cache directly.
 */

/**
 * applyAssistantDeltaToCache()
 *
 * Adds a delta chunk to an assistant message in the cache.
 *
 * If assistant message doesn’t exist yet, it creates it.
 * That makes streaming more robust.
 */
export function applyAssistantDeltaToCache(params: {
  qc: ReturnType<typeof useQueryClient>;
  conversationId: string;
  pageSize?: number;
  assistantMessageId: string;
  deltaText: string;
}) {
  const { qc, conversationId, assistantMessageId, deltaText } = params;
  const pageSize = params.pageSize ?? 50;

  qc.setQueryData<InfiniteData<MessagePage> | undefined>(
    chatMessagesInfiniteKey(conversationId, pageSize),
    (prev) => {
      const safe = prev ?? ensureInfiniteShape(undefined);

      // Find the assistant message if it already exists
      const flat = flattenInfiniteMessages(safe);
      const existing = flat.find((m) => m.id === assistantMessageId);

      // Build updated assistant message with appended text
      const nextMessage: ChatMessage = existing
        ? {
            ...existing,
            content_text: (existing.content_text ?? "") + deltaText,
            optimistic: existing.optimistic ?? true
          }
        : {
            // Create new message if not found
            id: assistantMessageId,
            role: "assistant",
            type: "chat",
            content_text: deltaText,
            content_json: null,
            created_at: new Date().toISOString(),
            client_message_id: null,
            optimistic: true
          };

      return upsertMessageInInfinite(safe, nextMessage, { preferNewestPage: true });
    }
  );
}

/**
 * finalizeAssistantMessageInCache()
 *
 * Marks assistant message as done.
 * UI can stop showing typing indicators.
 *
 * If you provide finalMessage from server, we store it (best).
 * Otherwise, we simply set optimistic=false on the existing cached message.
 */
export function finalizeAssistantMessageInCache(params: {
  qc: ReturnType<typeof useQueryClient>;
  conversationId: string;
  pageSize?: number;
  assistantMessageId: string;
  finalMessage?: ChatMessage;
}) {
  const { qc, conversationId, assistantMessageId, finalMessage } = params;
  const pageSize = params.pageSize ?? 50;

  qc.setQueryData<InfiniteData<MessagePage> | undefined>(
    chatMessagesInfiniteKey(conversationId, pageSize),
    (prev) => {
      if (!prev) return prev;

      // Best-case: replace with server final message
      if (finalMessage) {
        return upsertMessageInInfinite(prev, { ...finalMessage, optimistic: false }, { preferNewestPage: true });
      }

      // Otherwise: just flip optimistic flag
      const flat = flattenInfiniteMessages(prev);
      const existing = flat.find((m) => m.id === assistantMessageId);
      if (!existing) return prev;

      return upsertMessageInInfinite(prev, { ...existing, optimistic: false }, { preferNewestPage: true });
    }
  );
}

/* ============================================================================
 * 8) SEND MESSAGE MUTATION (Optimistic UI + Assistant placeholder)
 * ============================================================================
 *
 * Non technical explanation of flow:
 *
 * When user sends message:
 * 1) We immediately show the message in the UI (optimistic user message)
 * 2) We also immediately show an empty assistant bubble (placeholder)
 * 3) We send request to backend
 * 4) When backend replies, we replace fake messages with real saved messages
 * 5) If assistant is streaming, the placeholder bubble fills gradually
 *
 * Technical explanation:
 * - onMutate: optimistic insert into cache
 * - onError: rollback cache
 * - onSuccess: replace optimistic with server messages
 */

export function useSendChatMessageMutationInfinite(conversationId: string, pageSize = 50) {
  const qc = useQueryClient();

  return useMutation({
    /**
     * mutationFn
     *
     * Sends the message to backend.
     * The backend stores user message and may return assistant message.
     */
    mutationFn: async (input: {
      conversation_id: string;
      project_id?: string;
      message: string;
      client_message_id: string;
      llm_provider?: "hosted";
      llm_model?: string;
      force_pipeline?: boolean;
    }) =>
      apiFetchJson("/chat/send", {
        method: "POST",
        body: input,
        schema: SendResponseSchema
      }),

    /**
     * onMutate
     *
     * Runs immediately before the server request finishes.
     * This is where we do optimistic UI.
     */
    onMutate: async (input) => {
      if (!conversationId) return undefined;

      const key = chatMessagesInfiniteKey(conversationId, pageSize);

      // Stop ongoing fetch so it does not overwrite our optimistic update
      await qc.cancelQueries({ queryKey: key });

      // Snapshot existing cache for rollback if request fails
      const previous = qc.getQueryData<InfiniteData<MessagePage>>(key);

      const now = new Date().toISOString();

      /**
       * We generate fake ids so UI can render immediately.
       * Later, server returns real ids which replace these.
       */
      const optimisticUserId = `client:${input.client_message_id}`;

      const isAction = input.message.startsWith("__ACTION__:");

      // Optimistic user message bubble
      const optimisticUser: ChatMessage = {
        id: optimisticUserId,
        role: "user",
        type: isAction ? "action" : "chat",
        content_text: input.message,
        content_json: null,
        created_at: now,
        client_message_id: input.client_message_id,
        optimistic: true
      };

      // Update React Query cache so UI shows both bubbles immediately
      qc.setQueryData<InfiniteData<MessagePage> | undefined>(key, (prevData) => {
        const safe = prevData ?? ensureInfiniteShape(undefined);

        let next = upsertMessageInInfinite(safe, optimisticUser, { preferNewestPage: true });
        return next;
      });

      // Save context for onError/onSuccess
      return {
        previous,
        optimisticUserId
      };
    },

    /**
     * onError
     *
     * If the server request fails, we revert the optimistic UI changes.
     */
    onError: (_error, _input, context) => {
      if (!conversationId) return;
      const key = chatMessagesInfiniteKey(conversationId, pageSize);

      // Best rollback: restore previous full snapshot
      if (context?.previous) {
        qc.setQueryData(key, context.previous);
        return;
      }

      // Fallback rollback: remove the optimistic bubbles
      qc.setQueryData<InfiniteData<MessagePage> | undefined>(key, (prev) => {
        if (!prev) return prev;

        let next = prev;
        if (context?.optimisticUserId) next = removeMessageFromInfinite(next, context.optimisticUserId);
        return next;
      });
    },

    /**
     * onSuccess
     *
     * When server confirms it saved the message, we replace fake optimistic items
     * with the real server messages.
     */
    onSuccess: (data: SendResponse, _input, context) => {
      const key = chatMessagesInfiniteKey(conversationId, pageSize);

      qc.setQueryData<InfiniteData<MessagePage> | undefined>(key, (prev) => {
        const safe = prev ?? ensureInfiniteShape(undefined);

        // Replace optimistic user message with real server user_message
        let next = context?.optimisticUserId
          ? replaceMessageIdInInfinite(safe, context.optimisticUserId, {
              ...data.user_message,
              optimistic: false
            })
          : upsertMessageInInfinite(safe, { ...data.user_message, optimistic: false }, { preferNewestPage: true });

        /**
         * If server also returned assistant message instantly, replace placeholder.
         * If not returned, we keep the placeholder for streaming deltas.
         */
        if (data.assistant_message) {
          next = upsertMessageInInfinite(next, { ...data.assistant_message, optimistic: false }, { preferNewestPage: true });
        }

        return next;
      });

      // Refresh conversation list because last message preview / updated time can change
      void qc.invalidateQueries({ queryKey: ["chat-conversations"] });
    }
  });
}

/* ============================================================================
 * 9) HOW THE UI USES THIS (Short example)
 * ============================================================================
 *
 * Non technical explanation:
 * - messagesQuery fetches messages in pages
 * - flattenInfiniteMessages converts pages into one list for rendering
 * - fetchNextPage loads older messages when user scrolls up
 *
 * Technical example:
 *
 * const pageSize = 50;
 * const messagesQuery = useChatMessagesInfiniteQuery(conversationId, pageSize);
 * const messages = flattenInfiniteMessages(messagesQuery.data);
 *
 * if (messagesQuery.hasNextPage && !messagesQuery.isFetchingNextPage) {
 *   messagesQuery.fetchNextPage();
 * }
 *
 * Sending:
 *
 * const send = useSendChatMessageMutationInfinite(conversationId, pageSize);
 * send.mutate({
 *   conversation_id: conversationId,
 *   message: "Hello",
 *   client_message_id: crypto.randomUUID()
 * });
 *
 * Streaming:
 * When SSE/WS receives delta chunks, call applyAssistantDeltaToCache(...)
 * When stream ends, call finalizeAssistantMessageInCache(...)
 */
