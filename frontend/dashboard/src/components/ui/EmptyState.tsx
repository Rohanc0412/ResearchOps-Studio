import React from "react";

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-4 py-16 text-center">
      {icon && (
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-obsidian-accent-dim text-obsidian-accent">
          {icon}
        </div>
      )}
      <div className="space-y-1.5">
        <h3 className="font-display text-sm font-semibold text-obsidian-text">
          {title}
        </h3>
        {description && (
          <p className="max-w-sm text-sm text-obsidian-muted">{description}</p>
        )}
      </div>
      {action && <div className="pt-1">{action}</div>}
    </div>
  );
}
