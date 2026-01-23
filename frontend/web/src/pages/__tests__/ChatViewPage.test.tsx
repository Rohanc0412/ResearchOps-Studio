import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { ChatViewPage } from "../ChatViewPage";

const mockUseProjectQuery = vi.fn();
const mockUseChatConversationsQuery = vi.fn();
const mockUseChatMessagesInfiniteQuery = vi.fn();
const mockUseSendChatMessageMutationInfinite = vi.fn();
const mockUseCancelRunMutation = vi.fn();
const mockUseRetryRunMutation = vi.fn();
const mockUseSSE = vi.fn();

vi.mock("../../api/projects", () => ({
  useProjectQuery: (...args: unknown[]) => mockUseProjectQuery(...args)
}));

vi.mock("../../api/chat", () => ({
  useChatConversationsQuery: (...args: unknown[]) => mockUseChatConversationsQuery(...args),
  useChatMessagesInfiniteQuery: (...args: unknown[]) => mockUseChatMessagesInfiniteQuery(...args),
  useSendChatMessageMutationInfinite: (...args: unknown[]) => mockUseSendChatMessageMutationInfinite(...args)
}));

vi.mock("../../api/runs", () => ({
  useCancelRunMutation: (...args: unknown[]) => mockUseCancelRunMutation(...args),
  useRetryRunMutation: (...args: unknown[]) => mockUseRetryRunMutation(...args)
}));

vi.mock("../../hooks/useSSE", () => ({
  useSSE: (...args: unknown[]) => mockUseSSE(...args)
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/projects/proj-1/chats/chat-1"]}>
      <Routes>
        <Route path="/projects/:projectId/chats/:chatId" element={<ChatViewPage />} />
      </Routes>
    </MemoryRouter>
  );
}

function setupBaseMocks() {
  mockUseProjectQuery.mockReturnValue({
    isLoading: false,
    isError: false,
    data: { id: "proj-1", name: "Test Project", created_at: new Date().toISOString() }
  });
  mockUseChatConversationsQuery.mockReturnValue({
    isLoading: false,
    data: {
      items: [
        {
          id: "chat-1",
          title: "Chat One",
          created_at: new Date().toISOString(),
          last_message_at: new Date().toISOString()
        }
      ]
    }
  });
  mockUseCancelRunMutation.mockReturnValue({ mutateAsync: vi.fn() });
  mockUseRetryRunMutation.mockReturnValue({ mutateAsync: vi.fn() });
  mockUseSSE.mockReturnValue({
    events: [],
    state: "idle",
    lastError: null,
    latestStage: null,
    reset: vi.fn()
  });
}

describe("ChatViewPage", () => {
  it("loads chat history and renders message types", () => {
    setupBaseMocks();
    mockUseChatMessagesInfiniteQuery.mockReturnValue({
      data: {
        pages: [
          {
            items: [
              {
                id: "m1",
                role: "assistant",
                type: "chat",
                content_text: "Hello there",
                content_json: null,
                created_at: new Date().toISOString()
              },
              {
                id: "m2",
                role: "assistant",
                type: "error",
                content_text: "Something went wrong",
                content_json: null,
                created_at: new Date().toISOString()
              }
            ],
            next_cursor: null
          }
        ],
        pageParams: [undefined]
      }
    });
    mockUseSendChatMessageMutationInfinite.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });

    renderPage();

    expect(screen.getByText("Hello there")).toBeTruthy();
    expect(screen.getByText("Something went wrong")).toBeTruthy();
  });

  it("renders pipeline offer buttons and sends action tokens", async () => {
    setupBaseMocks();
    const mutateAsync = vi.fn().mockResolvedValue({ assistant_message: null });
    mockUseChatMessagesInfiniteQuery.mockReturnValue({
      data: {
        pages: [
          {
            items: [
              {
                id: "offer-1",
                role: "assistant",
                type: "pipeline_offer",
                content_text: "Do you want me to run the research pipeline?",
                content_json: {
                  offer: {
                    actions: [
                      { id: "run_pipeline", label: "Run research report" },
                      { id: "quick_answer", label: "Quick answer" }
                    ]
                  }
                },
                created_at: new Date().toISOString()
              }
            ],
            next_cursor: null
          }
        ],
        pageParams: [undefined]
      }
    });
    mockUseSendChatMessageMutationInfinite.mockReturnValue({ mutateAsync, isPending: false });

    renderPage();

    fireEvent.click(screen.getByText("Run research report"));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({ message: "__ACTION__:run_pipeline" })
      );
    });
  });

  it("renders run started message with link", () => {
    setupBaseMocks();
    mockUseChatMessagesInfiniteQuery.mockReturnValue({
      data: {
        pages: [
          {
            items: [
              {
                id: "run-start",
                role: "assistant",
                type: "run_started",
                content_text: "Starting a research run now.",
                content_json: { run_id: "run-1" },
                created_at: new Date().toISOString()
              }
            ],
            next_cursor: null
          }
        ],
        pageParams: [undefined]
      }
    });
    mockUseSendChatMessageMutationInfinite.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });

    renderPage();

    const link = screen.getByRole("link", { name: /open run viewer/i });
    expect(link.getAttribute("href")).toBe("/runs/run-1");
  });
});
