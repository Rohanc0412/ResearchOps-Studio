import { useEffect, useMemo, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { FolderKanban, FolderPlus, PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";

import { cx } from "../../utils/format";
import { useProjectsQuery } from "../../api/projects";

type ChatThreadSummary = {
  id: string;
  title: string;
  createdAt: string;
  messages?: unknown[];
};

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const projects = useProjectsQuery();
  const projectItems = useMemo(() => projects.data ?? [], [projects.data]);
  const [chatMap, setChatMap] = useState<Record<string, ChatThreadSummary[]>>({});
  const nav = useNavigate();
  const location = useLocation();

  const activeProjectId = useMemo(() => {
    const match = location.pathname.match(/^\/projects\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }, [location.pathname]);

  // Also detect active chat from URL
  const activeChatId = useMemo(() => {
    const match = location.pathname.match(/^\/projects\/[^/]+\/chats\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }, [location.pathname]);

  useEffect(() => {
    const next: Record<string, ChatThreadSummary[]> = {};
    for (const p of projectItems) {
      const key = `researchops.chats.${p.id}`;
      const raw = window.localStorage.getItem(key);
      if (!raw) {
        next[p.id] = [];
        continue;
      }
      try {
        const parsed = JSON.parse(raw) as ChatThreadSummary[];
        next[p.id] = Array.isArray(parsed) ? parsed : [];
      } catch {
        next[p.id] = [];
      }
    }
    setChatMap(next);
  }, [projectItems]);

  useEffect(() => {
    function handleUpdate() {
      const next: Record<string, ChatThreadSummary[]> = {};
      for (const p of projectItems) {
        const key = `researchops.chats.${p.id}`;
        const raw = window.localStorage.getItem(key);
        if (!raw) {
          next[p.id] = [];
          continue;
        }
        try {
          const parsed = JSON.parse(raw) as ChatThreadSummary[];
          next[p.id] = Array.isArray(parsed) ? parsed : [];
        } catch {
          next[p.id] = [];
        }
      }
      setChatMap(next);
    }

    window.addEventListener("researchops-chats-updated", handleUpdate);
    window.addEventListener("storage", handleUpdate);
    return () => {
      window.removeEventListener("researchops-chats-updated", handleUpdate);
      window.removeEventListener("storage", handleUpdate);
    };
  }, [projectItems]);

  function createChat(projectId: string) {
    const key = `researchops.chats.${projectId}`;
    const raw = window.localStorage.getItem(key);
    let existing: ChatThreadSummary[] = [];
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as ChatThreadSummary[];
        if (Array.isArray(parsed)) existing = parsed;
      } catch {
        existing = [];
      }
    }
    const now = new Date().toISOString();
    const chat = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      title: `Chat ${existing.length + 1}`,
      createdAt: now,
      messages: []
    };
    const next = [chat, ...existing];
    window.localStorage.setItem(key, JSON.stringify(next));
    window.dispatchEvent(new Event("researchops-chats-updated"));
    nav(`/projects/${encodeURIComponent(projectId)}/chats/${encodeURIComponent(chat.id)}`);
  }

  return (
    <aside
      className={cx(
        "group hidden flex-col border-r border-slate-900 bg-slate-950 transition-[width] duration-200 md:flex",
        collapsed ? "w-16" : "w-64"
      )}
    >
      <div
        className={cx(
          "flex items-center justify-between gap-2 px-4 py-4",
          collapsed && "flex-col gap-3 px-2"
        )}
      >
        <div className="flex items-center gap-2">
          <div className="relative rounded-md bg-sky-500/15 p-2 ring-1 ring-sky-500/30">
            <FolderKanban
              className={cx(
                "h-5 w-5 text-sky-200 transition-opacity",
                collapsed && "group-hover:opacity-0"
              )}
            />
            {collapsed ? (
              <button
                type="button"
                className="absolute inset-0 flex items-center justify-center text-slate-300 opacity-0 transition-opacity hover:text-slate-100 group-hover:opacity-100"
                onClick={() => setCollapsed(false)}
                title="Expand sidebar"
              >
                <PanelLeftOpen className="h-4 w-4" />
              </button>
            ) : null}
          </div>
          {!collapsed ? (
            <div>
              <div className="text-sm font-semibold text-slate-100">ResearchOps Studio</div>
              <div className="text-xs text-slate-500">Dashboard</div>
            </div>
          ) : null}
        </div>
        {!collapsed ? (
          <button
            type="button"
            className="rounded-md p-1 text-slate-400 transition-opacity hover:text-slate-200"
            onClick={() => setCollapsed(true)}
            title="Collapse sidebar"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        ) : null}
      </div>

      <nav className="flex flex-1 flex-col gap-3 px-2 py-2">
        {!collapsed ? (
          <div className="px-2 text-xs font-semibold uppercase text-slate-500">Projects</div>
        ) : null}
        <button
          type="button"
          className={cx(
            "flex items-center gap-2 rounded-md px-3 py-2 text-sm text-slate-200 hover:bg-slate-900",
            collapsed && "justify-center px-2 text-xs"
          )}
          onClick={() => nav("/projects?new=1")}
          title={collapsed ? "New project" : undefined}
        >
          <FolderPlus className="h-4 w-4" />
          {!collapsed ? "New project" : null}
        </button>
        <div className="flex flex-col gap-1">
          {projects.isLoading ? (
            <div className={cx("px-2 text-xs text-slate-600", collapsed && "text-center")}>Loading...</div>
          ) : projects.isError ? (
            <div className={cx("px-2 text-xs text-rose-400", collapsed && "text-center")}>Failed</div>
          ) : projectItems.length === 0 ? (
            <div className={cx("px-2 text-xs text-slate-600", collapsed && "text-center")}>No projects</div>
          ) : (
            projectItems.map((p) => {
              const isActive = p.id === activeProjectId;
              const chats = chatMap[p.id] ?? [];
              return (
                <div key={p.id} className="flex flex-col gap-1">
                  <NavLink
                    to={`/projects/${encodeURIComponent(p.id)}`}
                    className={({ isActive: routeActive }) =>
                      cx(
                        "flex items-center gap-2 rounded-md px-3 py-2 text-sm text-slate-300 hover:bg-slate-900 hover:text-slate-100",
                        collapsed && "justify-center px-2 text-xs",
                        routeActive && "bg-slate-900 text-slate-100"
                      )
                    }
                    title={collapsed ? p.name : undefined}
                  >
                    <span className="text-slate-400">
                      <FolderKanban className="h-4 w-4" />
                    </span>
                    {!collapsed ? p.name : null}
                  </NavLink>

                  {!collapsed ? (
                    <div className="ml-6 flex flex-col gap-1">
                      {isActive && chats.length > 0 ? (
                        <>
                          <div className="px-2 text-xs font-semibold uppercase text-slate-500">Recent</div>
                          {chats.slice(0, 3).map((chat) => (
                            <SidebarLink
                              key={chat.id}
                              to={`/projects/${encodeURIComponent(p.id)}/chats/${encodeURIComponent(chat.id)}`}
                              label={chat.title}
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
      </nav>
      <div className={cx("px-4 py-4 text-xs text-slate-600", collapsed && "px-3 text-center")}>v0.1</div>
    </aside>
  );
}

function SidebarLink({ to, label, collapsed }: { to: string; label: string; collapsed: boolean }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cx(
          "rounded-md px-3 py-2 text-sm text-slate-300 hover:bg-slate-900 hover:text-slate-100",
          collapsed && "px-2 text-center text-xs",
          isActive && "bg-slate-900 text-slate-100"
        )
      }
      title={collapsed ? label : undefined}
    >
      {collapsed ? label.slice(0, 2).toUpperCase() : label}
    </NavLink>
  );
}

