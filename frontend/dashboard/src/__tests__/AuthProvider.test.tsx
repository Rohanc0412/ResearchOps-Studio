import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { useContext } from "react";

import { AuthContext, AuthProvider } from "../auth/AuthProvider";

vi.mock("../api/client", () => ({
  apiBaseUrl: () => "/api",
}));

vi.mock("../api/auth", () => ({
  setAccessTokenGetter: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
}));

function Probe() {
  const auth = useContext(AuthContext);
  return (
    <div>
      <div>{auth?.isLoading ? "loading" : "ready"}</div>
      <div>{auth?.isAuthenticated ? "authenticated" : "anonymous"}</div>
      <button
        type="button"
        onClick={() => void auth?.register("alice", "alice@example.com", "password123")}
      >
        register
      </button>
    </div>
  );
}

describe("AuthProvider", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    window.localStorage.clear();
    window.sessionStorage.clear();
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does not refresh the session on boot when no access token is stored", async () => {
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("ready")).toBeInTheDocument();
    });

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refreshes the session on boot when a session token is stored", async () => {
    window.sessionStorage.setItem("researchops_access_token", "cached-token");
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: "fresh-token",
          user_id: "user-1",
          username: "alice",
          tenant_id: "tenant-1",
          roles: ["owner"],
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("ready")).toBeInTheDocument();
    });

    expect(fetchMock).toHaveBeenCalled();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/auth/refresh");
  });

  it("ignores a stale localStorage token on boot", async () => {
    window.localStorage.setItem("researchops_access_token", "stale-token");

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("ready")).toBeInTheDocument();
    });

    expect(screen.getByText("anonymous")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("researchops_access_token")).toBeNull();
  });

  it("does not authenticate or persist tokens after successful registration", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: "signup-token",
          user_id: "user-1",
          username: "alice",
          tenant_id: "tenant-1",
          roles: ["owner"],
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("ready")).toBeInTheDocument();
    });

    screen.getByRole("button", { name: "register" }).click();

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/auth/register",
        expect.objectContaining({ method: "POST" }),
      );
    });

    await waitFor(() => {
      expect(screen.getByText("anonymous")).toBeInTheDocument();
    });

    expect(window.sessionStorage.getItem("researchops_access_token")).toBeNull();
    expect(window.localStorage.getItem("researchops_access_token")).toBeNull();
  });
});
