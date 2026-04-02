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
  return <div>{auth?.isLoading ? "loading" : "ready"}</div>;
}

describe("AuthProvider", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    window.localStorage.clear();
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

  it("refreshes the session on boot when an access token is stored", async () => {
    window.localStorage.setItem("researchops_access_token", "cached-token");
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
});
