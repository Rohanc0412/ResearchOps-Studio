import React from "react";
import { cx } from "../../utils/format";

type CardVariant = "default" | "flat" | "highlighted";

const variantClasses: Record<CardVariant, string> = {
  default:     "border-obsidian-border-subtle bg-obsidian-surface-elevated shadow-surface",
  flat:        "border-transparent bg-obsidian-surface-elevated",
  highlighted: "border-obsidian-accent bg-obsidian-surface-elevated shadow-accent",
};

export function Card({
  className,
  variant = "default",
  children,
}: {
  className?: string;
  variant?: CardVariant;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cx(
        "rounded-xl border p-4",
        variantClasses[variant],
        className
      )}
    >
      {children}
    </div>
  );
}
