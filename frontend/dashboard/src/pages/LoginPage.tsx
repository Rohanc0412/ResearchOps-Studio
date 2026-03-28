import { CheckCircle, Shield, Brain, Sparkles, Zap } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "../auth/useAuth";
import { Button } from "../components/ui/Button";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Input } from "../components/ui/Input";

const FEATURES = [
  { icon: Brain,    label: "AI-powered research synthesis" },
  { icon: Sparkles, label: "Evidence management & tagging" },
  { icon: Zap,      label: "Fast, secure, team-ready" },
];

const MODE_TITLES: Record<string, string> = {
  login:    "Welcome back",
  register: "Create account",
  forgot:   "Reset password",
  reset:    "Set new password",
  mfa:      "Verify your identity",
};

export function LoginPage() {
  const auth = useAuth();
  const loc = useLocation();
  const from = (loc.state as { from?: string } | null)?.from ?? "/projects";
  const [mode, setMode] = useState<"login" | "register" | "forgot" | "reset">("login");
  const [suppressRedirect, setSuppressRedirect] = useState(false);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState("");
  const [mfaUser, setMfaUser] = useState<string | null>(null);
  const [resetToken, setResetToken] = useState("");
  const [resetPassword, setResetPassword] = useState("");
  const [resetConfirm, setResetConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

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

  if (auth.isAuthenticated && !suppressRedirect) return <Navigate to={from} replace />;

  const isRegister = mode === "register";
  const isForgot   = mode === "forgot";
  const isReset    = mode === "reset";
  const showMfa    = Boolean(mfaToken);
  const activeKey  = showMfa ? "mfa" : mode;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setIsSubmitting(true);
    try {
      if (mode === "register") {
        setSuppressRedirect(true);
        if (password.length < 8) throw new Error("Password must be at least 8 characters.");
        if (password !== confirmPassword) throw new Error("Passwords do not match.");
        await auth.register(username, email, password);
        try {
          window.sessionStorage.setItem(
            "researchops_signup_success",
            "Account created successfully! You can now sign in."
          );
        } catch { /* ignore */ }
        await auth.logout({ redirect: false });
        setSuppressRedirect(false);
        setMode("login");
        setPassword("");
        setConfirmPassword("");
        setSuccess("Account created successfully! You can now sign in.");
        return;
      }
      const result = await auth.login(username, password);
      if (result.mfaRequired) {
        setMfaToken(result.mfaToken);
        setMfaUser(result.username ?? username);
        setMfaCode("");
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

  async function onForgotSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setIsSubmitting(true);
    try {
      const result = await auth.requestPasswordReset(email);
      setResetToken(result.resetToken ?? "");
      setResetPassword("");
      setResetConfirm("");
      setMode("reset");
      if (result.resetToken) {
        setSuccess("Reset token generated. Enter a new password to continue.");
      } else {
        setSuccess("If the account exists, an OTP was generated. Enter it below to reset your password.");
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : "Password reset request failed.";
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function onResetSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setIsSubmitting(true);
    try {
      if (resetPassword.length < 8) throw new Error("Password must be at least 8 characters.");
      if (resetPassword !== resetConfirm) throw new Error("Passwords do not match.");
      await auth.confirmPasswordReset(resetToken, resetPassword);
      setSuccess("Password updated. Please sign in.");
      setResetPassword("");
      setResetConfirm("");
      setResetToken("");
      setMode("login");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Password reset failed.";
      setError(message);
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

  function switchMode(next: typeof mode) {
    setError(null);
    setSuccess(null);
    setIsSubmitting(false);
    setEmail("");
    setPassword("");
    setConfirmPassword("");
    setUsername("");
    setMode(next);
  }

  return (
    <div className="flex min-h-screen bg-obsidian-bg">
      {/* ── Left branding panel ─────────────────────────────────── */}
      <div className="hidden w-2/5 flex-col justify-between border-r border-obsidian-border px-12 py-16 lg:flex">
        {/* Logo */}
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-obsidian-accent">
            <Shield className="h-5 w-5 text-white" />
          </div>
          <span className="font-display text-lg font-semibold text-obsidian-text">
            ResearchOps Studio
          </span>
        </div>

        {/* Hero copy */}
        <div className="space-y-10">
          <div className="space-y-4">
            <h2 className="font-display text-4xl font-semibold leading-tight text-obsidian-text">
              Research, organised.<br />Insights, amplified.
            </h2>
            <p className="text-base leading-relaxed text-obsidian-muted">
              The AI-powered workspace for research operations teams. Run sessions,
              synthesise evidence, and surface what matters.
            </p>
          </div>

          <ul className="space-y-4">
            {FEATURES.map(({ icon: Icon, label }) => (
              <li key={label} className="flex items-center gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#1e1b2e]">
                  <Icon className="h-4 w-4 text-obsidian-accent" />
                </div>
                <span className="text-sm text-obsidian-muted">{label}</span>
              </li>
            ))}
          </ul>
        </div>

        <p className="text-xs text-obsidian-muted">
          &copy; {new Date().getFullYear()} ResearchOps Studio
        </p>
      </div>

      {/* ── Right form panel ────────────────────────────────────── */}
      <div className="flex flex-1 items-center justify-center px-6 py-12">
        <div className="w-full max-w-md animate-fade-in">
          {/* Card */}
          <div className="rounded-2xl border border-obsidian-border bg-obsidian-surface px-8 py-10 shadow-2xl">
            {/* Mode header */}
            <div className="mb-8">
              <h1 className="font-display text-2xl font-semibold text-obsidian-text">
                {MODE_TITLES[activeKey]}
              </h1>
              {!showMfa && (
                <p className="mt-1 text-sm text-obsidian-muted">
                  {mode === "login"    && "Sign in to your workspace"}
                  {mode === "register" && "Get started for free"}
                  {mode === "forgot"   && "We'll send you a one-time code"}
                  {mode === "reset"    && "Enter your OTP and choose a new password"}
                </p>
              )}
            </div>

            {/* Banners */}
            {error && <ErrorBanner message={error} className="mb-6" />}
            {success && (
              <div className="mb-6 flex items-start gap-3 rounded-lg border-[#1a3320] bg-[#142a1a] px-4 py-3">
                <CheckCircle className="mt-0.5 h-4 w-4 shrink-0 text-green-400" />
                <p className="text-sm font-sans text-green-400">{success}</p>
              </div>
            )}

            {/* ── MFA form ── */}
            {showMfa ? (
              <form onSubmit={onMfaSubmit} className="space-y-5">
                <div className="rounded-lg border border-[#2d2545] bg-[#1e1b2e] px-4 py-3">
                  <p className="text-sm text-obsidian-muted">
                    Enter the 6-digit code from your authenticator app
                    {mfaUser && (
                      <> for <span className="font-medium text-obsidian-text">{mfaUser}</span></>
                    )}.
                  </p>
                </div>

                <div className="space-y-1.5">
                  <label className="block text-xs font-medium text-obsidian-muted" htmlFor="mfa-code">
                    Verification code
                  </label>
                  <Input
                    id="mfa-code"
                    autoComplete="one-time-code"
                    value={mfaCode}
                    onChange={(e) => setMfaCode(e.target.value)}
                    placeholder="123456"
                  />
                </div>

                <Button type="submit" loading={isSubmitting} className="w-full">
                  {isSubmitting ? "Verifying…" : "Verify and sign in"}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  className="w-full"
                  onClick={() => { setMfaToken(null); setMfaCode(""); setMfaUser(null); }}
                >
                  Use a different account
                </Button>
              </form>

            /* ── Forgot form ── */
            ) : isForgot ? (
              <>
                <form onSubmit={onForgotSubmit} className="space-y-5">
                  <div className="space-y-1.5">
                    <label className="block text-xs font-medium text-obsidian-muted" htmlFor="forgot-email">
                      Email
                    </label>
                    <Input
                      id="forgot-email"
                      autoComplete="email"
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="you@company.com"
                      required
                    />
                  </div>
                  <Button type="submit" loading={isSubmitting} className="w-full">
                    {isSubmitting ? "Requesting…" : "Send OTP"}
                  </Button>
                </form>
                <div className="mt-6 flex flex-col gap-3 border-t border-obsidian-border pt-6 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-obsidian-muted">Remembered your password?</span>
                    <button
                      type="button"
                      onClick={() => switchMode("login")}
                      className="cursor-pointer font-medium text-obsidian-accent hover:brightness-125 focus:outline-none"
                    >
                      Back to sign in
                    </button>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-obsidian-muted">Already have an OTP?</span>
                    <button
                      type="button"
                      onClick={() => switchMode("reset")}
                      className="cursor-pointer font-medium text-obsidian-accent hover:brightness-125 focus:outline-none"
                    >
                      Enter OTP
                    </button>
                  </div>
                </div>
              </>

            /* ── Reset form ── */
            ) : isReset ? (
              <>
                <form onSubmit={onResetSubmit} className="space-y-5">
                  {resetToken && (
                    <div className="rounded-lg border border-obsidian-border bg-obsidian-bg px-3 py-2.5">
                      <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-obsidian-muted">
                        OTP (local dev)
                      </p>
                      <p className="break-all font-mono text-xs text-obsidian-accent">{resetToken}</p>
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <label className="block text-xs font-medium text-obsidian-muted" htmlFor="reset-token">
                      OTP code
                    </label>
                    <Input
                      id="reset-token"
                      autoComplete="one-time-code"
                      value={resetToken}
                      onChange={(e) => setResetToken(e.target.value)}
                      placeholder="Enter OTP"
                      required
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="block text-xs font-medium text-obsidian-muted" htmlFor="reset-pw">
                      New password
                    </label>
                    <Input
                      id="reset-pw"
                      autoComplete="new-password"
                      type="password"
                      value={resetPassword}
                      onChange={(e) => setResetPassword(e.target.value)}
                      placeholder="••••••••"
                      required
                    />
                    <p className="text-xs text-obsidian-muted">Minimum 8 characters</p>
                  </div>

                  <div className="space-y-1.5">
                    <label className="block text-xs font-medium text-obsidian-muted" htmlFor="reset-confirm">
                      Confirm new password
                    </label>
                    <Input
                      id="reset-confirm"
                      autoComplete="new-password"
                      type="password"
                      value={resetConfirm}
                      onChange={(e) => setResetConfirm(e.target.value)}
                      placeholder="••••••••"
                      required
                    />
                  </div>

                  <Button type="submit" loading={isSubmitting} className="w-full">
                    {isSubmitting ? "Updating…" : "Reset password"}
                  </Button>
                </form>
                <div className="mt-6 flex flex-col gap-3 border-t border-obsidian-border pt-6 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-obsidian-muted">Back to sign in?</span>
                    <button type="button" onClick={() => switchMode("login")}
                      className="cursor-pointer font-medium text-obsidian-accent hover:brightness-125 focus:outline-none">
                      Sign in
                    </button>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-obsidian-muted">Need a new OTP?</span>
                    <button type="button" onClick={() => switchMode("forgot")}
                      className="cursor-pointer font-medium text-obsidian-accent hover:brightness-125 focus:outline-none">
                      Send again
                    </button>
                  </div>
                </div>
              </>

            /* ── Login / Register form ── */
            ) : (
              <>
                <form onSubmit={onSubmit} className="space-y-5">
                  <div className="space-y-1.5">
                    <label className="block text-xs font-medium text-obsidian-muted" htmlFor="login-username">
                      Username or email
                    </label>
                    <Input
                      id="login-username"
                      autoComplete="username"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder="you@company.com"
                      required
                    />
                  </div>

                  {isRegister && (
                    <div className="space-y-1.5">
                      <label className="block text-xs font-medium text-obsidian-muted" htmlFor="login-email">
                        Email
                      </label>
                      <Input
                        id="login-email"
                        autoComplete="email"
                        type="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="you@company.com"
                        required
                      />
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <label className="block text-xs font-medium text-obsidian-muted" htmlFor="login-password">
                      Password
                    </label>
                    <Input
                      id="login-password"
                      autoComplete={isRegister ? "new-password" : "current-password"}
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••"
                      required
                    />
                    {isRegister && (
                      <p className="text-xs text-obsidian-muted">Minimum 8 characters</p>
                    )}
                  </div>

                  {isRegister && (
                    <div className="space-y-1.5">
                      <label className="block text-xs font-medium text-obsidian-muted" htmlFor="login-confirm">
                        Confirm password
                      </label>
                      <Input
                        id="login-confirm"
                        autoComplete="new-password"
                        type="password"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        placeholder="••••••••"
                        required
                      />
                    </div>
                  )}

                  <Button type="submit" loading={isSubmitting} className="w-full">
                    {isSubmitting
                      ? isRegister ? "Creating account…" : "Signing in…"
                      : isRegister ? "Create account"    : "Sign in"}
                  </Button>
                </form>

                {!isRegister && (
                  <div className="mt-4 text-center">
                    <button
                      type="button"
                      onClick={() => switchMode("forgot")}
                      className="cursor-pointer text-xs text-obsidian-muted hover:text-obsidian-accent focus:outline-none"
                    >
                      Forgot password?
                    </button>
                  </div>
                )}

                <div className="mt-6 flex items-center justify-between border-t border-obsidian-border pt-6 text-sm">
                  <span className="text-obsidian-muted">
                    {isRegister ? "Already have an account?" : "New to ResearchOps Studio?"}
                  </span>
                  <button
                    type="button"
                    onClick={() => switchMode(isRegister ? "login" : "register")}
                    className="cursor-pointer font-medium text-obsidian-accent hover:brightness-125 focus:outline-none"
                  >
                    {isRegister ? "Sign in" : "Create one"}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
