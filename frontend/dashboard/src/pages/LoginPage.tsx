import { CheckCircle, Shield, Brain, Sparkles, Zap } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "../auth/useAuth";

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
  const isForgot = mode === "forgot";
  const isReset = mode === "reset";
  const showMfa = Boolean(mfaToken);

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
        await auth.register(username, email, password);
        try {
          window.sessionStorage.setItem(
            "researchops_signup_success",
            "Account created successfully! You can now sign in."
          );
        } catch {
          // ignore storage failures
        }
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
      if (resetPassword.length < 8) {
        throw new Error("Password must be at least 8 characters.");
      }
      if (resetPassword !== resetConfirm) {
        throw new Error("Passwords do not match.");
      }
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
    setConfirmPassword("");
    setMode(next);
  }

  let subtitle = "Sign in to continue";
  if (showMfa) subtitle = "Verify your identity";
  else if (isRegister) subtitle = "Create your account";
  else if (isForgot) subtitle = "Request a password reset";
  else if (isReset) subtitle = "Set a new password";

  return (
    <div className="login-page-wrapper">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&family=DM+Sans:wght@400;500;600&display=swap');

        * {
          box-sizing: border-box;
        }

        .login-page-wrapper {
          position: relative;
          min-height: 100vh;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 2rem;
          background: #0b0b0e;
          font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif;
          overflow: hidden;
        }

        .login-page-wrapper::before {
          content: '';
          position: absolute;
          top: -50%;
          left: -50%;
          width: 200%;
          height: 200%;
          background:
            radial-gradient(circle at 20% 30%, rgba(99, 102, 241, 0.12) 0%, transparent 40%),
            radial-gradient(circle at 80% 70%, rgba(139, 92, 246, 0.10) 0%, transparent 40%),
            radial-gradient(circle at 50% 50%, rgba(59, 130, 246, 0.06) 0%, transparent 50%);
          animation: drift 20s ease-in-out infinite;
          pointer-events: none;
        }

        @keyframes drift {
          0%, 100% { transform: translate(0, 0) rotate(0deg); }
          33% { transform: translate(5%, -5%) rotate(2deg); }
          66% { transform: translate(-5%, 5%) rotate(-2deg); }
        }

        .login-page-wrapper::after {
          content: '';
          position: absolute;
          top: 20%;
          right: 15%;
          width: 300px;
          height: 300px;
          background: radial-gradient(circle, rgba(99, 102, 241, 0.15) 0%, transparent 70%);
          border-radius: 50%;
          filter: blur(60px);
          animation: float 8s ease-in-out infinite;
          pointer-events: none;
        }

        @keyframes float {
          0%, 100% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(-20px, -40px) scale(1.1); }
        }

        .login-card-container {
          position: relative;
          width: 100%;
          max-width: 480px;
          z-index: 10;
          animation: slideInUp 0.6s cubic-bezier(0.16, 1, 0.3, 1);
        }

        @keyframes slideInUp {
          from {
            opacity: 0;
            transform: translateY(30px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .login-card {
          background: rgba(20, 20, 26, 0.88);
          backdrop-filter: blur(24px) saturate(180%);
          -webkit-backdrop-filter: blur(24px) saturate(180%);
          border: 1px solid rgba(255, 255, 255, 0.09);
          border-radius: 24px;
          padding: 48px;
          box-shadow:
            0 24px 64px -12px rgba(0, 0, 0, 0.6),
            0 8px 16px -8px rgba(0, 0, 0, 0.4),
            0 0 0 1px rgba(255, 255, 255, 0.06),
            inset 0 1px 0 0 rgba(255, 255, 255, 0.08),
            inset 0 0 1px 0 rgba(255, 255, 255, 0.04);
          position: relative;
          overflow: hidden;
        }

        .login-card::before {
          content: '';
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          height: 140px;
          background: linear-gradient(180deg,
            rgba(255, 255, 255, 0.06) 0%,
            rgba(255, 255, 255, 0.02) 50%,
            transparent 100%);
          pointer-events: none;
          border-radius: 24px 24px 0 0;
        }

        .login-card::after {
          content: '';
          position: absolute;
          bottom: 0;
          left: 0;
          right: 0;
          height: 1px;
          background: linear-gradient(90deg,
            transparent 0%,
            rgba(99, 102, 241, 0.2) 50%,
            transparent 100%);
          pointer-events: none;
        }

        .brand-header {
          margin-bottom: 40px;
          position: relative;
        }

        .brand-logo-wrapper {
          display: flex;
          align-items: center;
          gap: 16px;
          margin-bottom: 8px;
        }

        .brand-icon-container {
          position: relative;
          width: 56px;
          height: 56px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: rgba(79, 70, 229, 0.15);
          border: 1px solid rgba(99, 102, 241, 0.25);
          border-radius: 16px;
        }

        .brand-icon {
          color: #818cf8;
          width: 28px;
          height: 28px;
        }

        .brand-text {
          flex: 1;
        }

        .brand-title {
          font-family: 'Syne', sans-serif;
          font-size: 28px;
          font-weight: 700;
          background: linear-gradient(135deg, #ffffff 0%, #a5b4fc 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
          letter-spacing: -0.02em;
          line-height: 1.2;
          margin: 0;
        }

        .brand-subtitle {
          font-size: 14px;
          color: rgba(203, 213, 225, 0.7);
          font-weight: 500;
          margin-top: 4px;
          letter-spacing: 0.01em;
        }

        .feature-pills {
          display: flex;
          gap: 8px;
          margin-top: 16px;
          flex-wrap: wrap;
        }

        .feature-pill {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 6px 12px;
          background: rgba(99, 102, 241, 0.08);
          border: 1px solid rgba(99, 102, 241, 0.2);
          border-radius: 20px;
          font-size: 11px;
          font-weight: 600;
          color: #c7d2fe;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          animation: fadeIn 0.6s ease-out backwards;
        }

        .feature-pill:nth-child(1) { animation-delay: 0.1s; }
        .feature-pill:nth-child(2) { animation-delay: 0.2s; }
        .feature-pill:nth-child(3) { animation-delay: 0.3s; }

        @keyframes fadeIn {
          from {
            opacity: 0;
            transform: translateY(10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .feature-pill svg {
          width: 12px;
          height: 12px;
        }

        .form-section {
          margin-top: 32px;
        }

        .form-group {
          margin-bottom: 20px;
        }

        .form-label {
          display: block;
          margin-bottom: 8px;
          font-size: 13px;
          font-weight: 600;
          color: #cbd5e1;
          letter-spacing: 0.01em;
        }

        .form-input {
          width: 100%;
          padding: 14px 16px;
          background: rgba(11, 11, 14, 0.7);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 12px;
          color: #e2e8f0;
          font-size: 15px;
          font-weight: 500;
          transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
          outline: none;
          font-family: inherit;
        }

        .form-input:focus {
          background: rgba(11, 11, 14, 0.9);
          border-color: rgba(99, 102, 241, 0.5);
          box-shadow:
            0 0 0 3px rgba(99, 102, 241, 0.1),
            0 0 20px rgba(99, 102, 241, 0.15),
            inset 0 1px 2px rgba(0, 0, 0, 0.3);
        }

        .form-input::placeholder {
          color: rgba(148, 163, 184, 0.5);
        }

        .form-hint {
          margin-top: 6px;
          font-size: 12px;
          color: rgba(148, 163, 184, 0.7);
        }

        .submit-button {
          width: 100%;
          padding: 16px;
          margin-top: 24px;
          background: #9580c4;
          border: none;
          border-radius: 12px;
          color: white;
          font-size: 15px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
          box-shadow:
            0 4px 15px rgba(149, 128, 196, 0.3),
            0 0 0 1px rgba(255, 255, 255, 0.1),
            inset 0 1px 0 rgba(255, 255, 255, 0.2);
          position: relative;
          overflow: hidden;
          font-family: inherit;
        }

        .submit-button::before {
          content: '';
          position: absolute;
          top: 0;
          left: -100%;
          width: 100%;
          height: 100%;
          background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent);
          transition: left 0.5s ease;
        }

        .submit-button:hover:not(:disabled) {
          background: #a792ce;
          transform: translateY(-2px);
          box-shadow:
            0 8px 25px rgba(149, 128, 196, 0.4),
            0 0 0 1px rgba(255, 255, 255, 0.15),
            inset 0 1px 0 rgba(255, 255, 255, 0.3);
        }

        .submit-button:hover:not(:disabled)::before {
          left: 100%;
        }

        .submit-button:active:not(:disabled) {
          transform: translateY(0);
          background: #8670b8;
        }

        .submit-button:disabled {
          opacity: 0.6;
          cursor: not-allowed;
          transform: none;
        }

        .toggle-mode {
          margin-top: 24px;
          padding-top: 24px;
          border-top: 1px solid rgba(255, 255, 255, 0.06);
          display: flex;
          align-items: center;
          justify-content: space-between;
          font-size: 14px;
        }

        .toggle-mode-text {
          color: rgba(203, 213, 225, 0.7);
        }

        .toggle-mode-button {
          background: none;
          border: none;
          color: #818cf8;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          padding: 8px 16px;
          border-radius: 8px;
          transition: all 0.2s ease;
          font-family: inherit;
        }

        .toggle-mode-button:hover {
          background: rgba(99, 102, 241, 0.1);
          color: #a5b4fc;
        }

        .success-banner, .error-banner {
          margin-bottom: 24px;
          padding: 16px;
          border-radius: 12px;
          display: flex;
          align-items: start;
          gap: 12px;
          animation: slideDown 0.4s cubic-bezier(0.16, 1, 0.3, 1);
          backdrop-filter: blur(8px);
        }

        .success-banner {
          background: rgba(16, 185, 129, 0.1);
          border: 1px solid rgba(16, 185, 129, 0.3);
          box-shadow: 0 4px 12px rgba(16, 185, 129, 0.1);
        }

        .error-banner {
          background: rgba(239, 68, 68, 0.1);
          border: 1px solid rgba(239, 68, 68, 0.3);
          box-shadow: 0 4px 12px rgba(239, 68, 68, 0.1);
        }

        @keyframes slideDown {
          from {
            opacity: 0;
            transform: translateY(-10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .success-icon {
          color: #34d399;
          width: 20px;
          height: 20px;
          flex-shrink: 0;
          margin-top: 1px;
        }

        .error-icon {
          color: #f87171;
          width: 20px;
          height: 20px;
          flex-shrink: 0;
          margin-top: 1px;
        }

        .success-text {
          color: #d1fae5;
          font-size: 14px;
          font-weight: 500;
          line-height: 1.5;
        }

        .error-text {
          color: #fecaca;
          font-size: 14px;
          font-weight: 500;
          line-height: 1.5;
        }

        .mfa-info-box {
          padding: 16px;
          background: rgba(99, 102, 241, 0.08);
          border: 1px solid rgba(99, 102, 241, 0.2);
          border-radius: 12px;
          margin-bottom: 24px;
          backdrop-filter: blur(8px);
        }

        .mfa-info-text {
          color: #c7d2fe;
          font-size: 14px;
          line-height: 1.6;
          margin: 0;
        }

        .mfa-user {
          color: #a5b4fc;
          font-weight: 600;
        }

        .reset-token-box {
          padding: 12px 16px;
          background: rgba(99, 102, 241, 0.06);
          border: 1px solid rgba(99, 102, 241, 0.15);
          border-radius: 10px;
          margin-bottom: 20px;
        }

        .reset-token-label {
          font-size: 11px;
          color: rgba(148, 163, 184, 0.6);
          text-transform: uppercase;
          letter-spacing: 0.05em;
          margin-bottom: 4px;
        }

        .reset-token-value {
          font-family: 'SF Mono', 'Fira Code', monospace;
          font-size: 12px;
          color: #a5b4fc;
          word-break: break-all;
        }

        .secondary-button {
          width: 100%;
          padding: 12px;
          margin-top: 12px;
          background: transparent;
          border: 1px solid rgba(255, 255, 255, 0.1);
          border-radius: 12px;
          color: #cbd5e1;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s ease;
          font-family: inherit;
        }

        .secondary-button:hover {
          background: rgba(255, 255, 255, 0.05);
          border-color: rgba(255, 255, 255, 0.15);
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        }

        .text-link {
          color: #818cf8;
          font-weight: 600;
          cursor: pointer;
          transition: color 0.2s ease;
        }

        .text-link:hover {
          color: #a5b4fc;
        }

        .forgot-link {
          margin-top: 16px;
          text-align: center;
        }

        .forgot-link .text-link {
          font-size: 13px;
          color: rgba(148, 163, 184, 0.6);
        }

        .forgot-link .text-link:hover {
          color: #818cf8;
        }

        @media (max-width: 640px) {
          .login-card {
            padding: 32px 24px;
          }

          .brand-title {
            font-size: 24px;
          }
        }
      `}</style>

      <div className="login-card-container">
        <div className="login-card">
          <div className="brand-header">
            <div className="brand-logo-wrapper">
              <div className="brand-icon-container">
                <Shield className="brand-icon" />
              </div>
              <div className="brand-text">
                <h1 className="brand-title">ResearchOps Studio</h1>
                <p className="brand-subtitle">{subtitle}</p>
              </div>
            </div>
            <div className="feature-pills">
              <div className="feature-pill">
                <Brain />
                AI-Powered
              </div>
              <div className="feature-pill">
                <Sparkles />
                Research Tools
              </div>
              <div className="feature-pill">
                <Zap />
                Fast & Secure
              </div>
            </div>
          </div>

          {error && (
            <div className="error-banner">
              <svg className="error-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
              <div className="error-text">{error}</div>
            </div>
          )}

          {success && (
            <div className="success-banner">
              <CheckCircle className="success-icon" />
              <div className="success-text">{success}</div>
            </div>
          )}

          {showMfa ? (
            <form className="form-section" onSubmit={onMfaSubmit}>
              <div className="mfa-info-box">
                <p className="mfa-info-text">
                  Enter the 6-digit code from your authenticator app
                  {mfaUser && <span className="mfa-user"> for {mfaUser}</span>}.
                </p>
              </div>
              <div className="form-group">
                <label className="form-label">Verification code</label>
                <input
                  className="form-input"
                  autoComplete="one-time-code"
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value)}
                  placeholder="123456"
                />
              </div>
              <button
                className="submit-button"
                type="submit"
                disabled={isSubmitting}
              >
                {isSubmitting ? "Verifying..." : "Verify and sign in"}
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={() => {
                  setMfaToken(null);
                  setMfaCode("");
                  setMfaUser(null);
                }}
              >
                Use a different account
              </button>
            </form>
          ) : isForgot ? (
            <>
              <form className="form-section" onSubmit={onForgotSubmit}>
                <div className="form-group">
                  <label className="form-label">Email</label>
                  <input
                    className="form-input"
                    autoComplete="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@company.com"
                    required
                  />
                </div>
                <button className="submit-button" type="submit" disabled={isSubmitting}>
                  {isSubmitting ? "Requesting..." : "Send OTP"}
                </button>
              </form>
              <div className="toggle-mode">
                <span className="toggle-mode-text">Remembered your password?</span>
                <span className="text-link" onClick={() => switchMode("login")}>
                  Back to sign in
                </span>
              </div>
               <div className="toggle-mode" style={{ marginTop: 8, paddingTop: 8, borderTopColor: "transparent" }}>
                 <span className="toggle-mode-text">Already have an OTP?</span>
                 <span className="text-link" onClick={() => switchMode("reset")}>
                   Enter OTP
                 </span>
               </div>
             </>
           ) : isReset ? (
             <>
              <form className="form-section" onSubmit={onResetSubmit}>
                {resetToken && (
                  <div className="reset-token-box">
                    <div className="reset-token-label">OTP (local dev)</div>
                    <div className="reset-token-value">{resetToken}</div>
                  </div>
                )}
                <div className="form-group">
                  <label className="form-label">OTP code</label>
                  <input
                    className="form-input"
                    autoComplete="one-time-code"
                    value={resetToken}
                    onChange={(e) => setResetToken(e.target.value)}
                    placeholder="Enter OTP"
                    required
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">New password</label>
                  <input
                    className="form-input"
                    autoComplete="new-password"
                    type="password"
                    value={resetPassword}
                    onChange={(e) => setResetPassword(e.target.value)}
                    placeholder="••••••••"
                    required
                  />
                  <div className="form-hint">Minimum 8 characters</div>
                </div>
                <div className="form-group">
                  <label className="form-label">Confirm new password</label>
                  <input
                    className="form-input"
                    autoComplete="new-password"
                    type="password"
                    value={resetConfirm}
                    onChange={(e) => setResetConfirm(e.target.value)}
                    placeholder="••••••••"
                    required
                  />
                </div>
                <button className="submit-button" type="submit" disabled={isSubmitting}>
                  {isSubmitting ? "Updating..." : "Reset password"}
                </button>
              </form>
               <div className="toggle-mode">
                 <span className="toggle-mode-text">Back to sign in?</span>
                 <span className="text-link" onClick={() => switchMode("login")}>
                   Sign in
                 </span>
               </div>
               <div className="toggle-mode" style={{ marginTop: 8, paddingTop: 8, borderTopColor: "transparent" }}>
                 <span className="toggle-mode-text">Need a new OTP?</span>
                 <span className="text-link" onClick={() => switchMode("forgot")}>
                   Send again
                 </span>
               </div>
             </>
           ) : (
             <>
               <form className="form-section" onSubmit={onSubmit}>
                 <div className="form-group">
                  <label className="form-label">Username or email</label>
                  <input
                    className="form-input"
                    autoComplete="username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="you@company.com"
                    required
                  />
                </div>
                {isRegister && (
                  <div className="form-group">
                    <label className="form-label">Email</label>
                    <input
                      className="form-input"
                      autoComplete="email"
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="you@company.com"
                      required
                    />
                  </div>
                )}
                <div className="form-group">
                  <label className="form-label">Password</label>
                  <input
                    className="form-input"
                    autoComplete={isRegister ? "new-password" : "current-password"}
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    required
                  />
                  {isRegister && (
                    <div className="form-hint">Minimum 8 characters</div>
                  )}
                </div>
                {isRegister && (
                  <div className="form-group">
                    <label className="form-label">Confirm password</label>
                    <input
                      className="form-input"
                      autoComplete="new-password"
                      type="password"
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      placeholder="••••••••"
                      required
                    />
                  </div>
                )}
                <button
                  className="submit-button"
                  type="submit"
                  disabled={isSubmitting}
                >
                  {isSubmitting
                    ? isRegister
                      ? "Creating account..."
                      : "Signing in..."
                    : isRegister
                      ? "Create account"
                      : "Sign in"}
                </button>
              </form>
              <div className="toggle-mode">
                <span className="toggle-mode-text">
                  {isRegister ? "Already have an account?" : "New to ResearchOps Studio?"}
                </span>
                <span className="text-link" onClick={() => switchMode(isRegister ? "login" : "register")}>
                  {isRegister ? "Sign in" : "Create one"}
                </span>
              </div>
              {!isRegister && (
                <div className="forgot-link">
                  <span className="text-link" onClick={() => switchMode("forgot")}>
                    Forgot password?
                  </span>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
