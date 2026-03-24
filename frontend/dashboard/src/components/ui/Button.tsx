import React from "react";
import { cx } from "../../utils/format";

export function Button({
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-md border border-sky-500 bg-sky-500 px-3 py-2 text-sm font-medium text-slate-100 transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  );
}
