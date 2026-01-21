import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiFetchJson } from "./client";
import { ChatConversationSchema, ChatMessageSchema, type ChatMessage } from "../types/dto";

const ConversationListSchema = z
  .object({
    items: z.array(ChatConversationSchema),
    next_cursor: z.string().nullable().optional()
  })
  .passthrough();

const MessageListSchema = z
  .object({
    items: z.array(ChatMessageSchema),
    next_cursor: z.string().nullable().optional()
  })
  .passthrough();

const SendResponseSchema = z
  .object({
    conversation_id: z.string().min(1),
    user_message: ChatMessageSchema,
    assistant_message: ChatMessageSchema.nullable().optional(),
    pending_action: z.record(z.unknown()).nullable().optional(),
    idempotent_replay: z.boolean().optional()
  })
  .passthrough();

type SendResponse = z.infer<typeof SendResponseSchema>;

function mergeChatMessages(existing: ChatMessage[], additions: ChatMessage[]) {
  const merged = new Map<string, ChatMessage>();
  for (const item of existing) merged.set(item.id, item);
  for (const item of additions) merged.set(item.id, item);
  const items = Array.from(merged.values());
  items.sort((a, b) => {
    const byTime = a.created_at.localeCompare(b.created_at);
    return byTime !== 0 ? byTime : a.id.localeCompare(b.id);
  });
  return items;
}

export function useChatConversationsQuery(projectId: string, limit = 50) {
  return useQuery({
    queryKey: ["chat-conversations", projectId, limit],
    queryFn: async () =>
      apiFetchJson(`/chat/conversations?project_id=${encodeURIComponent(projectId)}&limit=${limit}`, {
        schema: ConversationListSchema
      }),
    enabled: Boolean(projectId)
  });
}

export function useChatMessagesQuery(conversationId: string, limit = 200) {
  return useQuery({
    queryKey: ["chat-messages", conversationId, limit],
    queryFn: async () =>
      apiFetchJson(`/chat/conversations/${encodeURIComponent(conversationId)}/messages?limit=${limit}`, {
        schema: MessageListSchema
      }),
    enabled: Boolean(conversationId)
  });
}

export function useCreateConversationMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: { project_id?: string; title?: string | null }) =>
      apiFetchJson("/chat/conversations", {
        method: "POST",
        body: input,
        schema: ChatConversationSchema
      }),
    onSuccess: async (_, input) => {
      await qc.invalidateQueries({ queryKey: ["chat-conversations", input.project_id] });
    }
  });
}

export function useSendChatMessageMutation(conversationId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      conversation_id: string;
      project_id?: string;
      message: string;
      client_message_id: string;
      llm_provider?: "hosted";
      llm_model?: string;
    }) =>
      apiFetchJson("/chat/send", {
        method: "POST",
        body: input,
        schema: SendResponseSchema
      }),
    onSuccess: async (data: SendResponse) => {
      if (conversationId) {
        qc.setQueryData(
          ["chat-messages", conversationId, 200],
          (prev: z.infer<typeof MessageListSchema> | undefined) => {
            const existing = prev?.items ?? [];
            const additions = [data.user_message, data.assistant_message].filter(
              (item): item is ChatMessage => Boolean(item)
            );
            return {
              items: mergeChatMessages(existing, additions),
              next_cursor: prev?.next_cursor ?? null
            };
          }
        );
      }
      await qc.invalidateQueries({ queryKey: ["chat-conversations"] });
    }
  });
}
