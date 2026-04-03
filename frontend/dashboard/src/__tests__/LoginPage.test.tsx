import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { LoginPage } from "../pages/LoginPage";

const authState = {
  isLoading: false,
  isAuthenticated: false,
  user: null,
  accessToken: null,
  login: vi.fn(),
  verifyMfa: vi.fn(),
  register: vi.fn(),
  requestPasswordReset: vi.fn(),
  confirmPasswordReset: vi.fn(),
  logout: vi.fn(),
  clearSession: vi.fn(),
  refreshSession: vi.fn(),
};

vi.mock("../auth/useAuth", () => ({
  useAuth: () => authState,
}));

describe("LoginPage", () => {
  beforeEach(() => {
    Object.assign(authState, {
      isLoading: false,
      isAuthenticated: false,
      user: null,
      accessToken: null,
    });
    authState.login.mockReset();
    authState.verifyMfa.mockReset();
    authState.register.mockReset();
    authState.requestPasswordReset.mockReset();
    authState.confirmPasswordReset.mockReset();
    authState.logout.mockReset();
    authState.clearSession.mockReset();
    authState.refreshSession.mockReset();
    window.sessionStorage.clear();
  });

  it("returns to sign-in mode after successful registration", async () => {
    authState.register.mockResolvedValue(undefined);

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <LoginPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Create one" }));

    fireEvent.change(screen.getByLabelText("Username or email"), {
      target: { value: "alice" },
    });
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "alice@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password123" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "password123" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => {
      expect(authState.register).toHaveBeenCalledWith("alice", "alice@example.com", "password123");
    });

    expect(
      await screen.findByText("Account created successfully! You can now sign in."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create account" })).not.toBeInTheDocument();
  });
});
