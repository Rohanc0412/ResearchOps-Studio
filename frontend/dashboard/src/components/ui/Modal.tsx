import React, { useEffect } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { cx } from "../../utils/format";
import { Button } from "./Button";

export function Modal({
  open,
  title,
  children,
  onClose,
  className,
}: {
  open: boolean;
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  className?: string;
}) {
  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Panel */}
      <div
        className={cx(
          "relative w-full max-w-md animate-scale-in",
          "rounded-2xl border border-obsidian-border bg-obsidian-surface shadow-2xl",
          className
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-obsidian-border-subtle px-6 py-4">
          <h2 className="font-display text-base font-semibold text-obsidian-text">
            {title}
          </h2>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            aria-label="Close modal"
            className="!px-1.5 !py-1.5"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
        {/* Body */}
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>,
    document.body
  );
}
