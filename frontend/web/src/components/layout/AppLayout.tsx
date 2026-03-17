import { Outlet, useLocation } from "react-router-dom";

import { Sidebar } from "./Sidebar";
import { cx } from "../../utils/format";

export function AppLayout() {
  const location = useLocation();
  const isFullBleed = location.pathname.includes("/chats/");

  return (
    <div className="min-h-screen bg-slate-950 p-4 md:p-6">
      <div className="flex h-[calc(100vh-2rem)] overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 shadow-soft md:h-[calc(100vh-3rem)]">
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <Sidebar />
          <main
            className={cx(
              "flex-1 min-h-0 overflow-auto bg-slate-950",
              isFullBleed ? "p-0" : "px-6 py-6"
            )}
          >
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}
