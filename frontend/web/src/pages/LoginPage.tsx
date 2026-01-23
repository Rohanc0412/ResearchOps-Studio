import { Navigate, useLocation } from "react-router-dom";
import { Shield } from "lucide-react";

import { useAuth } from "../auth/useAuth";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";

export function LoginPage() {
  const auth = useAuth();
  const loc = useLocation();
  const from = (loc.state as { from?: string } | null)?.from ?? "/projects";

  if (auth.isAuthenticated) return <Navigate to={from} replace />;

  return (
    <div className="mx-auto flex min-h-screen max-w-lg items-center px-4">
      <Card className="w-full p-6">
        <div className="mb-6 flex items-center gap-3">
          <div className="rounded-lg bg-sky-500/15 p-3 ring-1 ring-sky-500/30">
            <Shield className="h-5 w-5 text-sky-200" />
          </div>
          <div>
            <div className="text-lg font-semibold text-slate-100">ResearchOps Studio</div>
            <div className="text-sm text-slate-400">Sign in to continue</div>
          </div>
        </div>
        <Button className="w-full" onClick={() => void auth.login()}>
          Login with OIDC
        </Button>
        <div className="mt-4 text-xs text-slate-500">
          This app uses OIDC Authorization Code + PKCE. Configure env vars in <code>.env</code>.
        </div>
      </Card>
    </div>
  );
}

