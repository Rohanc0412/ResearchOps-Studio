import { type FormEvent, useState } from "react";

import { useAuth } from "../auth/useAuth";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { disableMfa, startMfaEnroll, useMfaStatusQuery, verifyMfaEnroll } from "../api/mfa";

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
      const message = e instanceof Error ? e.message : "Verification failed.";
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

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <div>
        <div className="text-2xl font-semibold text-slate-100">Security</div>
        <div className="text-sm text-slate-400">Manage multi-factor authentication for your account.</div>
      </div>

      {error ? <ErrorBanner title="Security error" message={error} /> : null}
      {success ? (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-100">
          {success}
        </div>
      ) : null}

      <Card className="space-y-4 p-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold text-slate-100">Authenticator app (TOTP)</div>
            <div className="text-xs text-slate-500">
              {enabled ? "Enabled" : pending ? "Setup in progress" : "Not enabled"}
            </div>
          </div>
          {!enabled ? (
            <Button
              type="button"
              onClick={() => void handleStart()}
              disabled={isWorking || statusLoading}
            >
              {pending ? "Restart setup" : "Enable MFA"}
            </Button>
          ) : null}
        </div>

        {enroll ? (
          <form className="space-y-3" onSubmit={handleVerify}>
            <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3 text-xs text-slate-300">
              <div className="font-semibold text-slate-200">Setup details</div>
              <div className="mt-2">
                <span className="text-slate-400">Issuer:</span> {enroll.issuer}
              </div>
              <div className="mt-1">
                <span className="text-slate-400">Account:</span> {enroll.account_name}
              </div>
              <div className="mt-2 break-all">
                <span className="text-slate-400">Secret:</span> {enroll.secret}
              </div>
              <div className="mt-2 break-all text-slate-500">
                <span className="text-slate-400">OTP URI:</span> {enroll.otpauth_uri}
              </div>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-400">Verification code</label>
              <Input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="123456"
                autoComplete="one-time-code"
              />
            </div>
            <Button className="w-full" type="submit" disabled={isWorking}>
              {isWorking ? "Verifying..." : "Confirm and enable"}
            </Button>
          </form>
        ) : null}

        {enabled ? (
          <form className="space-y-3" onSubmit={handleDisable}>
            <div className="text-xs text-slate-500">
              Enter a current code to disable MFA.
            </div>
            <Input
              value={disableCode}
              onChange={(e) => setDisableCode(e.target.value)}
              placeholder="123456"
              autoComplete="one-time-code"
            />
            <Button className="w-full" variant="danger" type="submit" disabled={isWorking}>
              {isWorking ? "Disabling..." : "Disable MFA"}
            </Button>
          </form>
        ) : null}
      </Card>
    </div>
  );
}
