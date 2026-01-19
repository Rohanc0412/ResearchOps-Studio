import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { ProjectDetailPage } from "../ProjectDetailPage";

const mockUseProjectQuery = vi.fn();
const mockUseCreateRunMutation = vi.fn();
const mockUseCancelRunMutation = vi.fn();
const mockUseRetryRunMutation = vi.fn();
const mockUseSSE = vi.fn();
const mockApiFetchJson = vi.fn();

vi.mock("../../api/projects", () => ({
  useProjectQuery: (...args: unknown[]) => mockUseProjectQuery(...args)
}));

vi.mock("../../api/runs", () => ({
  useCreateRunMutation: (...args: unknown[]) => mockUseCreateRunMutation(...args),
  useCancelRunMutation: (...args: unknown[]) => mockUseCancelRunMutation(...args),
  useRetryRunMutation: (...args: unknown[]) => mockUseRetryRunMutation(...args)
}));

vi.mock("../../hooks/useSSE", () => ({
  useSSE: (...args: unknown[]) => mockUseSSE(...args)
}));

vi.mock("../../api/client", () => ({
  apiFetchJson: (...args: unknown[]) => mockApiFetchJson(...args)
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

describe("ProjectDetailPage run banner", () => {
  it("does not add run event messages to the chat", async () => {
    mockUseProjectQuery.mockReturnValue({
      isLoading: false,
      isError: false,
      data: { id: "proj-1", name: "Test Project", created_at: new Date().toISOString() }
    });
    mockUseCreateRunMutation.mockReturnValue({
      isPending: false,
      mutateAsync: vi.fn().mockResolvedValue({ id: "run-1" })
    });
    mockUseCancelRunMutation.mockReturnValue({ mutateAsync: vi.fn() });
    mockUseRetryRunMutation.mockReturnValue({ mutateAsync: vi.fn() });
    mockUseSSE.mockReturnValue({
      events: [
        {
          id: 1,
          ts: new Date().toISOString(),
          level: "info",
          stage: "retrieve",
          message: "Starting stage: retrieve",
          payload: { step: "create_run" }
        }
      ],
      state: "open",
      lastError: null,
      latestStage: null,
      reset: vi.fn()
    });

    renderPage();

    fireEvent.change(screen.getByPlaceholderText("Ask about this project..."), {
      target: { value: "What is LLM?" }
    });
    fireEvent.click(screen.getByText("Send"));

    await waitFor(() => {
      expect(screen.queryByText(/Starting stage: retrieve/i)).toBeNull();
    });
  });

  it("renders a banner and clears it on success", async () => {
    mockUseProjectQuery.mockReturnValue({
      isLoading: false,
      isError: false,
      data: { id: "proj-1", name: "Test Project", created_at: new Date().toISOString() }
    });
    mockUseCreateRunMutation.mockReturnValue({
      isPending: false,
      mutateAsync: vi.fn().mockResolvedValue({ id: "run-2" })
    });
    mockUseCancelRunMutation.mockReturnValue({ mutateAsync: vi.fn() });
    mockUseRetryRunMutation.mockReturnValue({ mutateAsync: vi.fn() });
    mockApiFetchJson.mockResolvedValueOnce([]);
    mockUseSSE.mockReturnValue({
      events: [
        {
          id: 2,
          ts: new Date().toISOString(),
          level: "info",
          stage: "export",
          message: "Finished stage: export",
          payload: { status: "succeeded" }
        }
      ],
      state: "open",
      lastError: null,
      latestStage: null,
      reset: vi.fn()
    });

    renderPage();

    fireEvent.change(screen.getByPlaceholderText("Ask about this project..."), {
      target: { value: "Summarize LLMs" }
    });
    fireEvent.click(screen.getByText("Send"));

    await waitFor(() => {
      expect(screen.queryByText(/Answer now/i)).toBeNull();
      expect(screen.getByText(/Run completed/i)).toBeTruthy();
    });
  });
});
