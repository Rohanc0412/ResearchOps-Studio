import { NavLink } from "react-router-dom";
import { FolderKanban } from "lucide-react";

import { cx } from "../../utils/format";

export function Sidebar() {
  return (
    <aside className="hidden w-64 flex-col border-r border-slate-900 bg-slate-950 md:flex">
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="rounded-md bg-sky-500/15 p-2 ring-1 ring-sky-500/30">
          <FolderKanban className="h-5 w-5 text-sky-200" />
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-100">ResearchOps Studio</div>
          <div className="text-xs text-slate-500">Dashboard</div>
        </div>
      </div>
      <nav className="flex flex-1 flex-col gap-1 px-2 py-2">
        <SidebarLink to="/projects" label="Projects" />
      </nav>
      <div className="px-4 py-4 text-xs text-slate-600">v0.1</div>
    </aside>
  );
}

function SidebarLink({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cx(
          "rounded-md px-3 py-2 text-sm text-slate-300 hover:bg-slate-900 hover:text-slate-100",
          isActive && "bg-slate-900 text-slate-100"
        )
      }
    >
      {label}
    </NavLink>
  );
}

