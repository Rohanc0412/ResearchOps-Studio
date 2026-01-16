import React, { createContext, useEffect, useMemo, useState } from "react";
import type { User } from "oidc-client-ts";

import { setAccessTokenGetter, setUnauthorizedHandler } from "../api/auth";
import { createUserManager, postLogoutRedirectUri } from "./oidc";

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

const userManager = createUserManager();

export function AuthProvider({ children }: { children: React.ReactNode }) {
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
        const existing = await userManager.getUser();
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
    const onUserLoaded = (u: User) => setUser(u);
    const onUserUnloaded = () => setUser(null);
    userManager.events.addUserLoaded(onUserLoaded);
    userManager.events.addUserUnloaded(onUserUnloaded);
    return () => {
      userManager.events.removeUserLoaded(onUserLoaded);
      userManager.events.removeUserUnloaded(onUserUnloaded);
    };
  }, []);

  async function login() {
    await userManager.signinRedirect();
  }

  async function clearSession() {
    await userManager.removeUser();
    setUser(null);
  }

  async function logout() {
    const uri = postLogoutRedirectUri();
    if (uri) await userManager.signoutRedirect({ post_logout_redirect_uri: uri });
    await clearSession();
    window.location.assign("/login");
  }

  const value = useMemo<AuthState>(
    () => ({ isLoading, isAuthenticated, user, accessToken, login, logout, clearSession }),
    [isLoading, isAuthenticated, user, accessToken]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export async function handleSigninCallback(): Promise<void> {
  await userManager.signinRedirectCallback();
}

