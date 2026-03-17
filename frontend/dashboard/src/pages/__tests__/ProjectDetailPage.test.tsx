import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { ProjectDetailPage } from "../ProjectDetailPage";

const mockUseProjectQuery = vi.fn();
const mockUseChatConversationsQuery = vi.fn();
const mockUseCreateConversationMutation = vi.fn();

vi.mock("../../api/projects", () => ({
  useProjectQuery: (...args: unknown[]) => mockUseProjectQuery(...args)
}));

vi.mock("../../api/chat", () => ({
  useChatConversationsQuery: (...args: unknown[]) => mockUseChatConversationsQuery(...args),
  useCreateConversationMutation: () => mockUseCreateConversationMutation()
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/projects/proj-1"]}>
      <Routes>
        <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("ProjectDetailPage conversations", () => {
  it("renders recent chats list", () => {
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
    mockUseCreateConversationMutation.mockReturnValue({ mutateAsync: vi.fn() });

    renderPage();

    expect(screen.getByText("Recent chats")).toBeTruthy();
    expect(screen.getByText("Chat One")).toBeTruthy();
  });

  it("creates a new chat from quick start", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ id: "chat-2" });
    mockUseProjectQuery.mockReturnValue({
      isLoading: false,
      isError: false,
      data: { id: "proj-1", name: "Test Project", created_at: new Date().toISOString() }
    });
    mockUseChatConversationsQuery.mockReturnValue({
      isLoading: false,
      data: { items: [] }
    });
    mockUseCreateConversationMutation.mockReturnValue({ mutateAsync });

    renderPage();

    fireEvent.change(screen.getByPlaceholderText("Start a new chat in Test Project..."), {
      target: { value: "Hello chat" }
    });
    fireEvent.click(screen.getByText("Start chat"));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        project_id: "proj-1",
        title: "Hello chat"
      });
    });
  });
});
