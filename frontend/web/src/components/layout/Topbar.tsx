import type { ReactNode } from "react";
import { LogOut, ShieldCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../../auth/useAuth";
import { useMeQuery } from "../../api/me";
import { Button } from "../ui/Button";
import { Badge } from "../ui/Badge";

export function Topbar({ actions }: { actions?: ReactNode | null }) {
  const auth = useAuth();
  const nav = useNavigate();
  const me = useMeQuery(auth.isAuthenticated);

  const roles = me.data?.roles ?? auth.user?.roles ?? [];
  const role = roles[0] ?? "viewer";
  const tenant = me.data?.tenant_id ?? auth.user?.tenant_id ?? "-";
  const displayName =
    me.data?.username ?? auth.user?.username ?? me.data?.user_id ?? auth.user?.user_id ?? "-";

  return (
    <header className="flex items-center justify-between border-b border-slate-800 bg-slate-950 px-6 py-4">
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-lg bg-sky-500" />
        <div>
          <div className="text-sm font-semibold text-slate-100">ResearchOps Studio</div>
          <div className="text-xs text-slate-500">Dashboard</div>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {actions ? (
          actions
        ) : (
          <>
            <div className="hidden text-right md:block">
              <div className="text-sm font-medium text-slate-100">{displayName}</div>
              <div className="text-xs text-slate-500">
                tenant <span className="text-slate-300">{tenant}</span>
              </div>
            </div>
            <Badge tone="info">{role}</Badge>
            <Button
              variant="secondary"
              onClick={() => nav("/security")}
              title="Security"
            >
              <ShieldCheck className="h-4 w-4" />
              <span className="hidden sm:inline">Security</span>
            </Button>
            <Button variant="secondary" onClick={() => void auth.logout()} title="Logout">
              <LogOut className="h-4 w-4" />
              <span className="hidden sm:inline">Logout</span>
            </Button>
          </>
        )}
      </div>
    </header>
  );
}
