import React from "react";
import { cx } from "../../utils/format";

type Variant = "primary" | "secondary" | "danger" | "ghost";

export function Button({
  variant = "primary",
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50";
  const variants: Record<Variant, string> = {
    primary: "bg-sky-500 text-white hover:bg-sky-400",
    secondary: "bg-slate-800 text-slate-100 hover:bg-slate-700",
    danger: "bg-rose-600 text-white hover:bg-rose-500",
    ghost: "bg-transparent text-slate-100 hover:bg-slate-900"
  };
  return <button className={cx(base, variants[variant], className)} {...props} />;
}

