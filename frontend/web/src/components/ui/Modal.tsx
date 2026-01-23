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
  className
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
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className={cx("relative w-full max-w-lg rounded-xl border border-slate-800 bg-slate-950 p-4 shadow-soft", className)}>
        <div className="mb-3 flex items-center justify-between">
          <div className="text-sm font-semibold text-slate-100">{title}</div>
          <Button variant="ghost" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </div>
        {children}
      </div>
    </div>,
    document.body
  );
}

