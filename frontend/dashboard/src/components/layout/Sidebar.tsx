import { useMemo, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  Folder,
  FolderPlus,
  LogOut,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
} from "lucide-react";

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
        "hidden flex-col border-r border-obsidian-border bg-obsidian-bg md:flex",
        "transition-[width] duration-200 ease-in-out",
        collapsed ? "w-14" : "w-60"
      )}
    >
      {/* Branding header */}
      <div
        className={cx(
          "flex h-14 shrink-0 items-center border-b border-obsidian-border-subtle px-3",
          collapsed ? "justify-center" : "justify-between"
        )}
      >
        {!collapsed && (
          <div className="flex items-center gap-2.5 overflow-hidden">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-obsidian-accent">
              <ShieldCheck className="h-4 w-4 text-white" />
            </div>
            <span className="truncate font-display text-sm font-semibold text-obsidian-text">
              ResearchOps
            </span>
          </div>
        )}
        {collapsed && (
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-obsidian-accent">
            <ShieldCheck className="h-4 w-4 text-white" />
          </div>
        )}
        {!collapsed && (
          <button
            type="button"
            onClick={() => setCollapsed(true)}
            title="Collapse sidebar"
            className="cursor-pointer rounded-md p-1 text-obsidian-muted hover:bg-obsidian-accent-dim hover:text-obsidian-text focus:outline-none"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex flex-1 flex-col overflow-y-auto px-2 py-3">
        {/* Workspace section */}
        {!collapsed && (
          <div className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-widest text-obsidian-muted">
            Workspace
          </div>
        )}

        {/* New project button */}
        <button
          type="button"
          onClick={() => nav("/projects?new=1")}
          title={collapsed ? "New project" : undefined}
          className={cx(
            "mb-1 flex cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-obsidian-muted",
            "hover:bg-obsidian-accent-dim hover:text-obsidian-text",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-obsidian-accent",
            collapsed && "justify-center px-0"
          )}
        >
          <FolderPlus className="h-4 w-4 shrink-0" />
          {!collapsed && <span>New project</span>}
        </button>

        {/* Project list */}
        <div className="flex flex-col gap-0.5">
          {projects.isLoading ? (
            <div className={cx("px-3 py-1 text-xs text-obsidian-muted", collapsed && "text-center")}>
              Loading…
            </div>
          ) : projects.isError ? (
            <div className={cx("px-3 py-1 text-xs text-red-400", collapsed && "text-center")}>
              Failed
            </div>
          ) : projectItems.length === 0 ? (
            <div className={cx("px-3 py-1 text-xs text-obsidian-muted", collapsed && "text-center")}>
              No projects
            </div>
          ) : (
            projectItems.map((p) => {
              const isActive = p.id === activeProjectId;
              return (
                <div key={p.id}>
                  <NavLink
                    to={`/projects/${encodeURIComponent(p.id)}`}
                    title={collapsed ? p.name : undefined}
                    className={({ isActive: routeActive }) =>
                      cx(
                        "relative flex items-center gap-2.5 rounded-lg py-2 text-sm",
                        "hover:bg-obsidian-accent-dim hover:text-obsidian-text",
                        "focus:outline-none focus-visible:ring-2 focus-visible:ring-obsidian-accent",
                        collapsed ? "justify-center px-0" : "px-3",
                        routeActive
                          ? "bg-obsidian-accent-dim text-obsidian-text"
                          : "text-obsidian-muted"
                      )
                    }
                  >
                    {({ isActive: routeActive }) => (
                      <>
                        {/* Active left bar */}
                        {routeActive && !collapsed && (
                          <span className="absolute left-0 top-1 h-[calc(100%-8px)] w-0.5 rounded-full bg-obsidian-accent" />
                        )}
                        <Folder
                          className={cx(
                            "h-4 w-4 shrink-0",
                            routeActive ? "text-obsidian-accent" : "text-obsidian-muted"
                          )}
                        />
                        {!collapsed && (
                          <span className="truncate">{p.name}</span>
                        )}
                      </>
                    )}
                  </NavLink>

                  {/* Recent chats under active project */}
                  {!collapsed && isActive && activeChats.length > 0 && (
                    <div className="ml-4 mt-0.5 flex flex-col gap-0.5 border-l border-obsidian-border-subtle pl-3">
                      {activeChats.slice(0, 3).map((chat) => (
                        <NavLink
                          key={chat.id}
                          to={`/projects/${encodeURIComponent(p.id)}/chats/${encodeURIComponent(chat.id)}`}
                          className={({ isActive: chatActive }) =>
                            cx(
                              "flex items-center gap-2 rounded-md px-2 py-1.5 text-xs",
                              "hover:bg-obsidian-accent-dim hover:text-obsidian-text",
                              "focus:outline-none focus-visible:ring-2 focus-visible:ring-obsidian-accent",
                              chatActive
                                ? "text-obsidian-text"
                                : "text-obsidian-muted"
                            )
                          }
                        >
                          <MessageSquare className="h-3 w-3 shrink-0" />
                          <span className="truncate">{chat.title ?? "Untitled chat"}</span>
                        </NavLink>
                      ))}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Account section — pinned to bottom */}
        <div className="mt-auto flex flex-col gap-0.5 border-t border-obsidian-border-subtle pt-3">
          {!collapsed && (
            <div className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-widest text-obsidian-muted">
              Account
            </div>
          )}

          <NavLink
            to="/security"
            title={collapsed ? "Security" : undefined}
            className={({ isActive }) =>
              cx(
                "flex items-center gap-2.5 rounded-lg py-2 text-sm",
                "hover:bg-obsidian-accent-dim hover:text-obsidian-text",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-obsidian-accent",
                collapsed ? "justify-center px-0" : "px-3",
                isActive
                  ? "bg-obsidian-accent-dim text-obsidian-text"
                  : "text-obsidian-muted"
              )
            }
          >
            <ShieldCheck
              className={cx(
                "h-4 w-4 shrink-0",
                securityActive ? "text-obsidian-accent" : "text-obsidian-muted"
              )}
            />
            {!collapsed && <span>Security</span>}
          </NavLink>

          <button
            type="button"
            onClick={() => void auth.logout()}
            title={collapsed ? "Logout" : undefined}
            className={cx(
              "flex cursor-pointer items-center gap-2.5 rounded-lg py-2 text-sm text-obsidian-muted",
              "hover:bg-obsidian-accent-dim hover:text-obsidian-text",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-obsidian-accent",
              collapsed ? "justify-center px-0" : "px-3"
            )}
          >
            <LogOut className="h-4 w-4 shrink-0" />
            {!collapsed && <span>Logout</span>}
          </button>
        </div>
      </nav>

      {/* Footer */}
      <div
        className={cx(
          "shrink-0 border-t border-obsidian-border-subtle px-4 py-3",
          collapsed && "flex justify-center"
        )}
      >
        {collapsed ? (
          <button
            type="button"
            onClick={() => setCollapsed(false)}
            title="Expand sidebar"
            className="cursor-pointer rounded-md p-1 text-obsidian-muted hover:bg-obsidian-accent-dim hover:text-obsidian-text focus:outline-none"
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        ) : (
          <span className="text-xs text-obsidian-muted">v0.1</span>
        )}
      </div>
    </aside>
  );
}
