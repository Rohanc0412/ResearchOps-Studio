import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { handleSigninCallback } from "../auth/AuthProvider";
import { Spinner } from "../components/ui/Spinner";
import { ErrorBanner } from "../components/ui/ErrorBanner";

export function OidcCallbackPage() {
  const nav = useNavigate();
  const [error, setError] = useState<null | string>(null);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      const params = new URLSearchParams(window.location.search);
      const code = params.get("code");
      if (!code) {
        setError("Missing authorization code in callback URL.");
        return;
      }

      const key = `oidc_callback_processed:${code}`;
      if (window.sessionStorage.getItem(key) === "1") {
        if (!cancelled) nav("/projects", { replace: true });
        return;
      }
      window.sessionStorage.setItem(key, "1");

      try {
        await withTimeout(handleSigninCallback(), 15_000);
        if (!cancelled) nav("/projects", { replace: true });
      } catch (e) {
        window.sessionStorage.removeItem(key);
        if (!cancelled) setError(e instanceof Error ? e.message : "OIDC callback failed");
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [nav]);

  if (error) {
    return (
      <div className="mx-auto flex min-h-screen max-w-lg items-center px-4">
        <ErrorBanner title="Login failed" message={error} />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <Spinner label="Completing sign-in…" />
    </div>
  );
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const t = window.setTimeout(() => reject(new Error("Sign-in timed out. Retry login.")), ms);
    promise
      .then((v) => resolve(v))
      .catch((e) => reject(e))
      .finally(() => window.clearTimeout(t));
  });
}
