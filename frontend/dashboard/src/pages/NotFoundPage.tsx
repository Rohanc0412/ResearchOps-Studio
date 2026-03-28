import { Link, useLocation } from "react-router-dom";
import { FolderOpen } from "lucide-react";

import { Button } from "../components/ui/Button";

export function NotFoundPage() {
  const { pathname } = useLocation();

  return (
    <div className="flex flex-col items-center justify-center py-24 gap-6 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-[#1e1b2e]">
        <FolderOpen className="h-7 w-7 text-obsidian-accent" />
      </div>
      <div>
        <h1 className="font-display text-2xl font-semibold text-obsidian-text">Page not found</h1>
        <p className="mt-2 text-sm text-obsidian-muted">
          <span className="font-mono">{pathname}</span> doesn't exist.
        </p>
      </div>
      <Link to="/projects">
        <Button>Go to Projects</Button>
      </Link>
    </div>
  );
}
