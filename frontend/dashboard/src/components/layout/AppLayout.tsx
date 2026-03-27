import { Outlet, useLocation } from "react-router-dom";

import { Sidebar } from "./Sidebar";
import { cx } from "../../utils/format";

export function AppLayout() {
  const location = useLocation();
  const isFullBleed = location.pathname.includes("/chats/");

  return (
    <div className="flex h-screen overflow-hidden bg-obsidian-bg">
      <Sidebar />
      <main
        className={cx(
          "flex min-h-0 flex-1 flex-col overflow-auto bg-obsidian-bg",
          isFullBleed ? "p-0" : "px-8 py-8"
        )}
      >
        <Outlet />
      </main>
    </div>
  );
}
