import { LogOut } from "lucide-react";

import { useAuth } from "../../auth/useAuth";
import { useMeQuery } from "../../api/me";
import { Button } from "../ui/Button";
import { Badge } from "../ui/Badge";

export function Topbar() {
  const auth = useAuth();
  const me = useMeQuery(auth.isAuthenticated);

  const roles = me.data?.roles ?? [];
  const role = roles[0] ?? "viewer";
  const tenant = me.data?.tenant_id ?? "—";
  const profile = auth.user?.profile as Record<string, unknown> | undefined;
  const email =
    me.data?.email ??
    (typeof profile?.["email"] === "string" ? profile["email"] : undefined) ??
    (typeof profile?.["preferred_username"] === "string" ? profile["preferred_username"] : undefined) ??
    "—";

  return (
    <header className="flex items-center justify-between border-b border-slate-900 bg-slate-950 px-4 py-3">
      <div className="text-sm text-slate-400">{me.isLoading ? "Loading identity…" : " "}</div>
      <div className="flex items-center gap-3">
        <div className="hidden text-right md:block">
          <div className="text-sm font-medium text-slate-100">{email}</div>
          <div className="text-xs text-slate-500">
            tenant <span className="text-slate-300">{tenant}</span>
          </div>
        </div>
        <Badge tone="info">{role}</Badge>
        <Button variant="secondary" onClick={() => void auth.logout()} title="Logout">
          <LogOut className="h-4 w-4" />
          <span className="hidden sm:inline">Logout</span>
        </Button>
      </div>
    </header>
  );
}
