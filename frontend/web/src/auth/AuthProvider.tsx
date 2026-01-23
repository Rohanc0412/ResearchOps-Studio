import React, { createContext, useEffect, useMemo, useState } from "react";
import type { User } from "oidc-client-ts";

import { setAccessTokenGetter, setUnauthorizedHandler } from "../api/auth";
import { createUserManager, postLogoutRedirectUri } from "./oidc";
import { ErrorBanner } from "../components/ui/ErrorBanner";

export type AuthState = {
  isLoading: boolean;
  isAuthenticated: boolean;
  user: User | null;
  accessToken: string | null;
  login: () => Promise<void>;
  logout: () => Promise<void>;
  clearSession: () => Promise<void>;
};

export const AuthContext = createContext<AuthState | null>(null);

let userManager: ReturnType<typeof createUserManager> | null = null;
function requireUserManager() {
  if (!userManager) userManager = createUserManager();
  return userManager;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  let managerError: Error | null = null;
  let manager: ReturnType<typeof createUserManager> | null = null;
  try {
    manager = requireUserManager();
  } catch (e) {
    managerError = e instanceof Error ? e : new Error("OIDC config error.");
  }

  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const accessToken = user?.access_token ?? null;
  const isAuthenticated = Boolean(accessToken);

  useEffect(() => {
    setAccessTokenGetter(() => accessToken);
  }, [accessToken]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      void clearSession().finally(() => {
        window.location.assign("/login");
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      try {
        if (!manager || managerError) return;
        const existing = await manager.getUser();
        if (!cancelled) setUser(existing);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void init();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!manager || managerError) return;
    const onUserLoaded = (u: User) => setUser(u);
    const onUserUnloaded = () => setUser(null);
    manager.events.addUserLoaded(onUserLoaded);
    manager.events.addUserUnloaded(onUserUnloaded);
    return () => {
      manager.events.removeUserLoaded(onUserLoaded);
      manager.events.removeUserUnloaded(onUserUnloaded);
    };
  }, [manager, managerError]);

  async function login() {
    if (!manager) throw new Error("OIDC config error.");
    await manager.signinRedirect();
  }

  async function clearSession() {
    if (!manager) return;
    await manager.removeUser();
    setUser(null);
  }

  async function logout() {
    if (!manager) return;
    const uri = postLogoutRedirectUri();
    if (uri) await manager.signoutRedirect({ post_logout_redirect_uri: uri });
    await clearSession();
    window.location.assign("/login");
  }

  const value = useMemo<AuthState>(
    () => ({ isLoading, isAuthenticated, user, accessToken, login, logout, clearSession }),
    [isLoading, isAuthenticated, user, accessToken]
  );

  if (managerError) {
    return (
      <div className="mx-auto flex min-h-screen max-w-2xl items-center p-6">
        <ErrorBanner title="Auth config error" message={managerError.message} />
      </div>
    );
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export async function handleSigninCallback(): Promise<void> {
  await requireUserManager().signinRedirectCallback();
}

