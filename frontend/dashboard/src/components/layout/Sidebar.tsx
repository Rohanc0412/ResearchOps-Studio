import { useMemo, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { Folder, FolderPlus, LogOut, PanelLeftClose, PanelLeftOpen, ShieldCheck } from "lucide-react";

import { useChatConversationsQuery } from "../../api/chat";
import { cx } from "../../utils/format";
import { useProjectsQuery } from "../../api/projects";
import { useAuth } from "../../auth/useAuth";

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const auth = useAuth();
  const projects = useProjectsQuery();
  const projectItems = useMemo(() => projects.data ?? [], [projects.data]);
  const nav = useNavigate();
  const location = useLocation();

  const activeProjectId = useMemo(() => {
    const match = location.pathname.match(/^\/projects\/([^/]+)/);
    return match?.[1] ? decodeURIComponent(match[1]) : null;
  }, [location.pathname]);

  const securityActive = location.pathname.startsWith("/security");

  const activeChatsQuery = useChatConversationsQuery(activeProjectId ?? "", 20);
  const activeChats = activeChatsQuery.data?.items ?? [];

  return (
    <aside
      className={cx(
        "group hidden flex-col border-r border-white/[0.06] bg-[#0b0b0e] transition-[width] duration-200 md:flex",
        collapsed ? "w-16" : "w-64"
      )}
    >
      {/* Branding header */}
      <div
        className={cx(
          "flex items-center px-3 py-3",
          collapsed ? "justify-center" : "justify-between"
        )}
      >
        {!collapsed && (
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-500">
              <ShieldCheck className="h-[18px] w-[18px] text-white" />
            </div>
            <span className="text-sm font-semibold text-slate-100">ResearchOps Studio</span>
          </div>
        )}
        <button
          type="button"
          className="p-1 text-slate-400 transition hover:text-slate-200 focus:outline-none"
          onClick={() => setCollapsed(!collapsed)}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex flex-1 flex-col gap-3 px-2 py-2">
        {!collapsed ? (
          <div className="px-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Projects</div>
        ) : null}

        <button
          type="button"
          className={cx(
            "flex items-center gap-2 px-3 py-2 text-sm text-slate-300 focus:outline-none",
            collapsed && "justify-center px-2 text-xs"
          )}
          onClick={() => nav("/projects?new=1")}
          title={collapsed ? "New project" : undefined}
        >
          <FolderPlus className="h-[18px] w-[18px] text-slate-500" />
          {!collapsed ? "New project" : null}
        </button>

        <div className="flex flex-col gap-1">
          {projects.isLoading ? (
            <div className={cx("px-2 text-xs text-slate-500", collapsed && "text-center")}>Loading...</div>
          ) : projects.isError ? (
            <div className={cx("px-2 text-xs text-rose-400", collapsed && "text-center")}>Failed</div>
          ) : projectItems.length === 0 ? (
            <div className={cx("px-2 text-xs text-slate-500", collapsed && "text-center")}>No projects</div>
          ) : (
            projectItems.map((p) => {
              const isActive = p.id === activeProjectId;
              return (
                <div key={p.id} className="flex flex-col gap-1">
                  <NavLink
                    to={`/projects/${encodeURIComponent(p.id)}`}
                    className={({ isActive: routeActive }) =>
                      cx(
                        "flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-300 hover:bg-[rgba(149,128,196,0.1)] hover:text-slate-100",
                        collapsed && "justify-center px-2 text-xs",
                        routeActive && "bg-[rgba(99,102,241,0.15)] text-slate-100"
                      )
                    }
                    title={collapsed ? p.name : undefined}
                  >
                    <span className={isActive ? "text-indigo-400" : "text-slate-400"}>
                      <Folder className="h-[18px] w-[18px]" />
                    </span>
                    {!collapsed ? p.name : null}
                  </NavLink>

                  {!collapsed ? (
                    <div className="ml-6 flex flex-col gap-1">
                      {isActive && activeChats.length > 0 ? (
                        <>
                          <div className="px-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Recent</div>
                          {activeChats.slice(0, 3).map((chat) => (
                            <SidebarLink
                              key={chat.id}
                              to={`/projects/${encodeURIComponent(p.id)}/chats/${encodeURIComponent(chat.id)}`}
                              label={chat.title ?? "Untitled chat"}
                              collapsed={collapsed}
                            />
                          ))}
                        </>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })
          )}
        </div>

        {/* Account section */}
        <div className="mt-4 flex flex-col gap-1 border-t border-white/[0.04] pt-3">
          {!collapsed ? (
            <div className="px-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Account</div>
          ) : null}
          <NavLink
            to="/security"
            className={({ isActive }) =>
              cx(
                "flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-300 hover:bg-[rgba(149,128,196,0.1)] hover:text-slate-100",
                collapsed && "justify-center px-2 text-xs",
                isActive && "bg-[rgba(99,102,241,0.15)] text-slate-100"
              )
            }
            title={collapsed ? "Security" : undefined}
          >
            <span className={securityActive ? "text-indigo-400" : "text-slate-400"}>
              <ShieldCheck className="h-[18px] w-[18px]" />
            </span>
            {!collapsed ? "Security" : null}
          </NavLink>
          <button
            type="button"
            className={cx(
              "flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-300 hover:bg-[rgba(149,128,196,0.1)] hover:text-slate-100 focus:outline-none",
              collapsed && "justify-center px-2 text-xs"
            )}
            onClick={() => void auth.logout()}
            title={collapsed ? "Logout" : undefined}
          >
            <span className="text-slate-400">
              <LogOut className="h-[18px] w-[18px]" />
            </span>
            {!collapsed ? "Logout" : null}
          </button>
        </div>
      </nav>

      {/* Version footer */}
      <div className={cx("px-4 py-4 text-xs text-slate-500", collapsed && "px-3 text-center")}>v0.1</div>
    </aside>
  );
}

function SidebarLink({ to, label, collapsed }: { to: string; label: string; collapsed: boolean }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cx(
          "rounded-lg px-3 py-2 text-sm text-slate-300 hover:bg-[rgba(149,128,196,0.1)] hover:text-slate-100",
          collapsed && "px-2 text-center text-xs",
          isActive && "bg-[rgba(99,102,241,0.15)] text-slate-100"
        )
      }
      title={collapsed ? label : undefined}
    >
      {collapsed ? label.slice(0, 2).toUpperCase() : label}
    </NavLink>
  );
}
