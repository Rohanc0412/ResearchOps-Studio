import { Navigate, useLocation } from "react-router-dom";
import { CheckCircle, Shield } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { useAuth } from "../auth/useAuth";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { ErrorBanner } from "../components/ui/ErrorBanner";

declare global {
  interface Window {
    google?: {
      accounts?: {
        id?: {
          initialize: (options: {
            client_id: string;
            callback: (response: { credential?: string }) => void;
            ux_mode?: "popup" | "redirect";
            auto_select?: boolean;
          }) => void;
          renderButton: (
            container: HTMLElement,
            options: { theme?: string; size?: string; shape?: string; text?: string }
          ) => void;
        };
      };
    };
  }
}

export function LoginPage() {
  const auth = useAuth();
  const loc = useLocation();
  const from = (loc.state as { from?: string } | null)?.from ?? "/projects";
  const [mode, setMode] = useState<"login" | "register">("login");
  const [suppressRedirect, setSuppressRedirect] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState("");
  const [mfaUser, setMfaUser] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const googleButtonRef = useRef<HTMLDivElement | null>(null);
  const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID?.trim() ?? "";
  const [googleReady, setGoogleReady] = useState(false);

  useEffect(() => {
    try {
      const message = window.sessionStorage.getItem("researchops_signup_success");
      if (message) {
        window.sessionStorage.removeItem("researchops_signup_success");
        setSuccess(message);
      }
    } catch {
      // ignore storage failures
    }
  }, []);

  useEffect(() => {
    if (!googleClientId) return;
    let cancelled = false;
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = () => {
      if (!cancelled) setGoogleReady(true);
    };
    script.onerror = () => {
      if (!cancelled) setError("Google sign-in is unavailable right now.");
    };
    document.head.appendChild(script);
    return () => {
      cancelled = true;
      document.head.removeChild(script);
    };
  }, [googleClientId]);

  useEffect(() => {
    if (!googleReady || !googleClientId) return;
    if (!window.google?.accounts?.id || !googleButtonRef.current) return;
    window.google.accounts.id.initialize({
      client_id: googleClientId,
      ux_mode: "popup",
      auto_select: false,
      callback: async (response) => {
        if (!response.credential) {
          setError("Google sign-in failed. Try again.");
          return;
        }
        setError(null);
        setSuccess(null);
        setIsSubmitting(true);
        try {
          const result = await auth.loginWithGoogle(response.credential);
          if (result.mfaRequired) {
            setMfaToken(result.mfaToken);
            setMfaUser(result.username ?? null);
            setMfaCode("");
          }
        } catch (e) {
          const message = e instanceof Error ? e.message : "Google sign-in failed. Try again.";
          setError(message);
        } finally {
          setIsSubmitting(false);
        }
      }
    });
    googleButtonRef.current.innerHTML = "";
    window.google.accounts.id.renderButton(googleButtonRef.current, {
      theme: "outline",
      size: "large",
      shape: "pill",
      text: "continue_with"
    });
  }, [googleReady, googleClientId, auth]);

  if (auth.isAuthenticated && !suppressRedirect) return <Navigate to={from} replace />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setIsSubmitting(true);
    try {
      if (mode === "register") {
        setSuppressRedirect(true);
        if (password.length < 8) {
          throw new Error("Password must be at least 8 characters.");
        }
        if (password !== confirmPassword) {
          throw new Error("Passwords do not match.");
        }
        await auth.register(username, password);
        try {
          window.sessionStorage.setItem(
            "researchops_signup_success",
            "Account created. Please sign in."
          );
        } catch {
          // ignore storage failures
        }
        await auth.logout();
        return;
      } else {
        const result = await auth.login(username, password);
        if (result.mfaRequired) {
          setMfaToken(result.mfaToken);
          setMfaUser(result.username ?? username);
          setMfaCode("");
        }
      }
    } catch (e) {
      const message =
        e instanceof Error
          ? e.message
          : mode === "register"
            ? "Sign up failed. Try again."
            : "Login failed. Try again.";
      setError(message);
      setSuppressRedirect(false);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function onMfaSubmit(event: FormEvent) {
    event.preventDefault();
    if (!mfaToken) return;
    setError(null);
    setIsSubmitting(true);
    try {
      await auth.verifyMfa(mfaToken, mfaCode);
    } catch (e) {
      const message = e instanceof Error ? e.message : "MFA verification failed.";
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  const isRegister = mode === "register";
  const showMfa = Boolean(mfaToken);

  return (
    <div className="mx-auto flex min-h-screen max-w-lg items-center px-4">
      <Card className="w-full p-6">
        <div className="mb-6 flex items-center gap-3">
          <div className="rounded-lg bg-sky-500/15 p-3 ring-1 ring-sky-500/30">
            <Shield className="h-5 w-5 text-sky-200" />
          </div>
          <div>
            <div className="text-lg font-semibold text-slate-100">ResearchOps Studio</div>
            <div className="text-sm text-slate-400">
              {isRegister ? "Create your account" : "Sign in to continue"}
            </div>
          </div>
        </div>
        {error ? (
          <ErrorBanner
            title={showMfa ? "Verification failed" : isRegister ? "Sign up failed" : "Login failed"}
            message={error}
          />
        ) : null}
        {success ? (
          <div className="mt-3 flex items-start gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-emerald-100">
            <CheckCircle className="mt-0.5 h-4 w-4 text-emerald-200" />
            <div className="text-sm font-semibold">{success}</div>
          </div>
        ) : null}
        {showMfa ? (
          <form className="mt-4 space-y-3" onSubmit={onMfaSubmit}>
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 text-xs text-slate-300">
              Enter the 6-digit code from your authenticator app
              {mfaUser ? <span className="text-slate-400"> for {mfaUser}</span> : null}.
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-400">Verification code</label>
              <Input
                autoComplete="one-time-code"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
                placeholder="123456"
              />
            </div>
            <Button className="w-full" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Verifying..." : "Verify and sign in"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="w-full text-xs text-slate-300"
              onClick={() => {
                setMfaToken(null);
                setMfaCode("");
                setMfaUser(null);
              }}
            >
              Use a different account
            </Button>
          </form>
        ) : (
          <>
            {googleClientId ? (
              <div className="mt-4 space-y-3">
                <div ref={googleButtonRef} className="flex justify-center" />
                <div className="flex items-center gap-3 text-xs text-slate-500">
                  <div className="h-px flex-1 bg-slate-800" />
                  <span>or continue with email</span>
                  <div className="h-px flex-1 bg-slate-800" />
                </div>
              </div>
            ) : null}
            <form className="mt-4 space-y-3" onSubmit={onSubmit}>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-400">
                  Username or email
                </label>
                <Input
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="you@company.com"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-400">Password</label>
                <Input
                  autoComplete={isRegister ? "new-password" : "current-password"}
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="********"
                />
                {isRegister ? (
                  <div className="mt-1 text-xs text-slate-500">Minimum 8 characters.</div>
                ) : null}
              </div>
              {isRegister ? (
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-400">
                    Confirm password
                  </label>
                  <Input
                    autoComplete="new-password"
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="********"
                  />
                </div>
              ) : null}
              <Button className="w-full" type="submit" disabled={isSubmitting}>
                {isSubmitting
                  ? isRegister
                    ? "Creating account..."
                    : "Signing in..."
                  : isRegister
                    ? "Create account"
                    : "Sign in"}
              </Button>
            </form>
            <div className="mt-4 flex items-center justify-between text-xs text-slate-400">
              <span>{isRegister ? "Already have an account?" : "New to ResearchOps Studio?"}</span>
              <Button
                type="button"
                variant="ghost"
                className="px-2 py-1 text-xs text-slate-200"
                onClick={() => {
                  setError(null);
                  setSuccess(null);
                  setIsSubmitting(false);
                  setConfirmPassword("");
                  setMode(isRegister ? "login" : "register");
                }}
              >
                {isRegister ? "Sign in" : "Create one"}
              </Button>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
