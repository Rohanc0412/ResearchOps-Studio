import React, { createContext, useEffect, useMemo, useState } from "react";

import { setAccessTokenGetter, setUnauthorizedHandler } from "../api/auth";
import { apiBaseUrl } from "../api/client";
import { ErrorBanner } from "../components/ui/ErrorBanner";

type AuthUser = {
  user_id: string;
  username: string;
  tenant_id: string;
  roles: string[];
};

export type AuthState = {
  isLoading: boolean;
  isAuthenticated: boolean;
  user: AuthUser | null;
  accessToken: string | null;
  login: (username: string, password: string) => Promise<LoginResult>;
  loginWithGoogle: (idToken: string) => Promise<LoginResult>;
  verifyMfa: (mfaToken: string, code: string) => Promise<void>;
  register: (username: string, password: string, tenantId?: string) => Promise<void>;
  logout: (opts?: { redirect?: boolean }) => Promise<void>;
  clearSession: () => Promise<void>;
  refreshSession: () => Promise<void>;
};

export type LoginResult =
  | { mfaRequired: false }
  | { mfaRequired: true; mfaToken: string; username?: string };

export const AuthContext = createContext<AuthState | null>(null);

const STORAGE_KEY = "researchops_access_token";

let baseUrlError: Error | null = null;
let baseUrl: string | null = null;
try {
  baseUrl = apiBaseUrl();
} catch (e) {
  baseUrlError = e instanceof Error ? e : new Error("Missing API base URL");
}

async function authFetch(path: string, init?: RequestInit): Promise<Response> {
  if (!baseUrl) throw baseUrlError ?? new Error("Missing API base URL");
  const url = `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = new Headers(init?.headers);
  if (!headers.has("content-type") && init?.body && typeof init.body === "string") {
    headers.set("content-type", "application/json");
  }
  headers.set("accept", headers.get("accept") ?? "application/json");
  return fetch(url, { ...init, headers, credentials: init?.credentials ?? "include" });
}

async function parseJson(response: Response): Promise<Record<string, unknown>> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as Record<string, unknown>;
  }
  return {};
}

function coerceRoles(raw: unknown): string[] {
  if (Array.isArray(raw)) return raw.filter((r): r is string => typeof r === "string");
  if (typeof raw === "string") {
    return raw
      .split(",")
      .map((r) => r.trim())
      .filter(Boolean);
  }
  return [];
}

function mapAuthUser(payload: Record<string, unknown>): AuthUser | null {
  const user_id = typeof payload.user_id === "string" ? payload.user_id : "";
  const username = typeof payload.username === "string" ? payload.username : user_id;
  const tenant_id = typeof payload.tenant_id === "string" ? payload.tenant_id : "";
  const roles = coerceRoles(payload.roles);
  if (!user_id || !tenant_id) return null;
  return { user_id, username, tenant_id, roles };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [accessToken, setAccessToken] = useState<string | null>(() => {
    try {
      return window.localStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  });
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const isAuthenticated = Boolean(accessToken);

  useEffect(() => {
    setAccessTokenGetter(() => accessToken);
    try {
      if (accessToken) {
        window.localStorage.setItem(STORAGE_KEY, accessToken);
      } else {
        window.localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // ignore storage failures
    }
  }, [accessToken]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      void refreshSession().catch(() => {
        void clearSession().finally(() => {
          window.location.assign("/login");
        });
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        await refreshSession();
      } catch {
        await clearSession();
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    void init();
    return () => {
      cancelled = true;
    };
  }, []);

  async function login(username: string, password: string): Promise<LoginResult> {
    const response = await authFetch("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password })
    });
    const payload = await parseJson(response);
    if (!response.ok) {
      const message =
        typeof payload.detail === "string" ? payload.detail : "Login failed. Check credentials.";
      throw new Error(message);
    }
    const mfaRequired = payload.mfa_required === true;
    if (mfaRequired) {
      const token = typeof payload.mfa_token === "string" ? payload.mfa_token : "";
      if (!token) throw new Error("Missing MFA token");
      const mfaUser = typeof payload.username === "string" ? payload.username : undefined;
      return { mfaRequired: true, mfaToken: token, username: mfaUser };
    }
    const token = typeof payload.access_token === "string" ? payload.access_token : "";
    if (!token) throw new Error("Missing access token");
    setAccessToken(token);
    setUser(mapAuthUser(payload));
    return { mfaRequired: false };
  }

  async function loginWithGoogle(idToken: string): Promise<LoginResult> {
    const response = await authFetch("/auth/google", {
      method: "POST",
      body: JSON.stringify({ id_token: idToken })
    });
    const payload = await parseJson(response);
    if (!response.ok) {
      const message =
        typeof payload.detail === "string"
          ? payload.detail
          : "Google login failed. Try again.";
      throw new Error(message);
    }
    const mfaRequired = payload.mfa_required === true;
    if (mfaRequired) {
      const token = typeof payload.mfa_token === "string" ? payload.mfa_token : "";
      if (!token) throw new Error("Missing MFA token");
      const mfaUser = typeof payload.username === "string" ? payload.username : undefined;
      return { mfaRequired: true, mfaToken: token, username: mfaUser };
    }
    const token = typeof payload.access_token === "string" ? payload.access_token : "";
    if (!token) throw new Error("Missing access token");
    setAccessToken(token);
    setUser(mapAuthUser(payload));
    return { mfaRequired: false };
  }

  async function verifyMfa(mfaToken: string, code: string): Promise<void> {
    const response = await authFetch("/auth/mfa/verify", {
      method: "POST",
      body: JSON.stringify({ mfa_token: mfaToken, code })
    });
    const payload = await parseJson(response);
    if (!response.ok) {
      const message =
        typeof payload.detail === "string" ? payload.detail : "MFA verification failed.";
      throw new Error(message);
    }
    const token = typeof payload.access_token === "string" ? payload.access_token : "";
    if (!token) throw new Error("Missing access token");
    setAccessToken(token);
    setUser(mapAuthUser(payload));
  }

  async function register(username: string, password: string, tenantId?: string) {
    const response = await authFetch("/auth/register", {
      method: "POST",
      body: JSON.stringify({
        username,
        password,
        ...(tenantId ? { tenant_id: tenantId } : {})
      })
    });
    const payload = await parseJson(response);
    if (!response.ok) {
      const message =
        typeof payload.detail === "string" ? payload.detail : "Sign up failed. Try again.";
      throw new Error(message);
    }
    const token = typeof payload.access_token === "string" ? payload.access_token : "";
    if (!token) throw new Error("Missing access token");
    setAccessToken(token);
    setUser(mapAuthUser(payload));
  }

  async function refreshSession() {
    const response = await authFetch("/auth/refresh", { method: "POST" });
    const payload = await parseJson(response);
    if (!response.ok) {
      throw new Error("Unable to refresh session");
    }
    const token = typeof payload.access_token === "string" ? payload.access_token : "";
    if (!token) throw new Error("Missing access token");
    setAccessToken(token);
    setUser(mapAuthUser(payload));
  }

  async function clearSession() {
    setAccessToken(null);
    setUser(null);
  }

  async function logout(opts?: { redirect?: boolean }) {
    await authFetch("/auth/logout", { method: "POST" });
    await clearSession();
    if (opts?.redirect === false) return;
    window.location.assign("/login");
  }

  const value = useMemo<AuthState>(
    () => ({
      isLoading,
      isAuthenticated,
      user,
      accessToken,
      login,
      loginWithGoogle,
      verifyMfa,
      register,
      logout,
      clearSession,
      refreshSession
    }),
    [isLoading, isAuthenticated, user, accessToken]
  );

  if (baseUrlError) {
    return (
      <div className="mx-auto flex min-h-screen max-w-2xl items-center p-6">
        <ErrorBanner title="Auth config error" message={baseUrlError.message} />
      </div>
    );
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
