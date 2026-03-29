import { type FormEvent, useState } from "react";
import { CheckCircle, Copy, ShieldCheck, ShieldOff } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";

import { useAuth } from "../auth/useAuth";
import { disableMfa, startMfaEnroll, useMfaStatusQuery, verifyMfaEnroll } from "../api/mfa";
import { Button } from "../components/ui/Button";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Input } from "../components/ui/Input";

export function SecurityPage() {
  const auth = useAuth();
  const statusQuery = useMfaStatusQuery(auth.isAuthenticated);
  const [enroll, setEnroll] = useState<{
    secret: string;
    otpauth_uri: string;
    issuer: string;
    account_name: string;
    period: number;
    digits: number;
  } | null>(null);
  const [code, setCode] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isWorking, setIsWorking] = useState(false);
  const [copied, setCopied] = useState(false);

  const enabled = statusQuery.data?.enabled ?? false;
  const pending = statusQuery.data?.pending ?? false;
  const statusLoading = statusQuery.isLoading;

  async function handleStart() {
    setError(null);
    setSuccess(null);
    setIsWorking(true);
    try {
      const data = await startMfaEnroll();
      setEnroll(data);
      setSuccess("Scan the secret in your authenticator app and enter the code below.");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unable to start MFA enrollment.";
      setError(message);
    } finally {
      setIsWorking(false);
    }
  }

  async function handleVerify(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setIsWorking(true);
    try {
      await verifyMfaEnroll(code);
      setCode("");
      setEnroll(null);
      await statusQuery.refetch();
      setSuccess("MFA is enabled.");
    } catch (e) {
      const raw = e instanceof Error ? e.message : "";
      const message = raw.includes("401")
        ? "Invalid verification code. Please check your authenticator app and try again."
        : raw || "Verification failed.";
      setCode("");
      setError(message);
    } finally {
      setIsWorking(false);
    }
  }

  async function handleDisable(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setIsWorking(true);
    try {
      await disableMfa(disableCode);
      setDisableCode("");
      await statusQuery.refetch();
      setSuccess("MFA is disabled.");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Disable failed.";
      setError(message);
    } finally {
      setIsWorking(false);
    }
  }

  function copySecret(text: string) {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-8">
      {/* Page header */}
      <div>
        <h1 className="font-display text-[28px] font-semibold leading-tight text-obsidian-text">
          Security
        </h1>
        <p className="mt-1 text-sm text-obsidian-muted">
          Manage multi-factor authentication for your account.
        </p>
      </div>

      {/* Banners */}
      {error && <ErrorBanner title="Security error" message={error} />}
      {success && (
        <div className="flex items-start gap-3 rounded-lg border-[#1a3320] bg-[#142a1a] px-4 py-3">
          <CheckCircle className="mt-0.5 h-4 w-4 shrink-0 text-green-400" />
          <p className="text-sm font-sans text-green-400">{success}</p>
        </div>
      )}

      {/* MFA card */}
      <div className="overflow-hidden rounded-xl border border-obsidian-border bg-obsidian-surface-elevated">
        {/* Card header row */}
        <div className="flex items-center justify-between gap-4 px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#1e1b2e]">
              {enabled ? (
                <ShieldCheck className="h-4 w-4 text-obsidian-accent" />
              ) : (
                <ShieldOff className="h-4 w-4 text-obsidian-muted" />
              )}
            </div>
            <div>
              <div className="text-sm font-medium text-obsidian-text">
                Authenticator app (TOTP)
              </div>
              <div className="mt-0.5 flex items-center gap-1.5">
                {enabled ? (
                  <>
                    <span className="h-1.5 w-1.5 rounded-full bg-green-400" />
                    <span className="text-xs text-green-400">Enabled</span>
                  </>
                ) : pending ? (
                  <>
                    <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                    <span className="text-xs text-amber-400">Setup in progress</span>
                  </>
                ) : (
                  <>
                    <span className="h-1.5 w-1.5 rounded-full bg-obsidian-muted" />
                    <span className="text-xs text-obsidian-muted">Not enabled</span>
                  </>
                )}
              </div>
            </div>
          </div>

          {!enabled && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void handleStart()}
              disabled={isWorking || statusLoading}
              loading={isWorking && !enroll}
            >
              {pending ? "Restart setup" : "Enable MFA"}
            </Button>
          )}
        </div>

        {/* Enroll flow */}
        {enroll && (
          <form
            className="flex flex-col gap-5 border-t border-obsidian-border px-6 py-5"
            onSubmit={handleVerify}
          >
            {/* QR code */}
            <div className="flex flex-col items-center gap-3">
              <div className="rounded-xl border border-obsidian-border bg-white p-3">
                <QRCodeSVG value={enroll.otpauth_uri} size={160} />
              </div>
              <p className="text-center text-xs text-obsidian-muted">
                Scan with your authenticator app (Google Authenticator, Authy, 1Password…)
              </p>
            </div>

            {/* Secret block */}
            <div className="space-y-1.5">
              <div className="text-[11px] font-semibold uppercase tracking-widest text-obsidian-muted">
                Secret
              </div>
              <div className="flex items-center gap-2 rounded-lg border border-obsidian-border bg-obsidian-bg px-3 py-2.5">
                <code data-testid="mfa-secret" className="flex-1 break-all font-mono text-sm text-obsidian-text">
                  {enroll.secret}
                </code>
                <button
                  type="button"
                  onClick={() => copySecret(enroll.secret)}
                  title="Copy secret"
                  className="shrink-0 cursor-pointer rounded-md p-1 text-obsidian-muted hover:bg-[#1e1b2e] hover:text-obsidian-text focus:outline-none"
                >
                  {copied ? (
                    <CheckCircle className="h-3.5 w-3.5 text-green-400" />
                  ) : (
                    <Copy className="h-3.5 w-3.5" />
                  )}
                </button>
              </div>
            </div>

            {/* OTP URI */}
            <div className="space-y-1.5">
              <div className="text-[11px] font-semibold uppercase tracking-widest text-obsidian-muted">
                OTP URI
              </div>
              <p className="truncate font-mono text-xs text-obsidian-muted" title={enroll.otpauth_uri}>
                {enroll.otpauth_uri}
              </p>
            </div>

            {/* Metadata */}
            <div className="flex gap-6 text-xs">
              <div>
                <span className="text-obsidian-muted">Issuer: </span>
                <span className="font-mono text-obsidian-text">{enroll.issuer}</span>
              </div>
              <div>
                <span className="text-obsidian-muted">Account: </span>
                <span className="font-mono text-obsidian-text">{enroll.account_name}</span>
              </div>
              <div>
                <span className="text-obsidian-muted">Period: </span>
                <span className="font-mono text-obsidian-text">{enroll.period}s</span>
              </div>
            </div>

            {/* Verify input */}
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-obsidian-muted" htmlFor="enroll-code">
                Verification code
              </label>
              <Input
                id="enroll-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="123456"
                autoComplete="one-time-code"
              />
            </div>

            <Button type="submit" loading={isWorking} className="w-full">
              {isWorking ? "Verifying…" : "Confirm and enable"}
            </Button>
          </form>
        )}

        {/* Disable flow */}
        {enabled && (
          <form
            className="flex flex-col gap-4 border-t border-obsidian-border px-6 py-5"
            onSubmit={handleDisable}
          >
            <p className="text-sm text-obsidian-muted">
              Enter a current TOTP code to disable multi-factor authentication.
            </p>
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-obsidian-muted" htmlFor="disable-code">
                Current code
              </label>
              <Input
                id="disable-code"
                value={disableCode}
                onChange={(e) => setDisableCode(e.target.value)}
                placeholder="123456"
                autoComplete="one-time-code"
              />
            </div>
            <Button
              type="submit"
              variant="danger"
              loading={isWorking}
              className="w-full"
            >
              {isWorking ? "Disabling…" : "Disable MFA"}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
