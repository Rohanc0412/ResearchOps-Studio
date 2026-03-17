import React from "react";
import { cx } from "../../utils/format";

type Variant = "primary" | "secondary" | "danger" | "ghost";

export function Button({
  variant = "primary",
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-md border border-sky-500 bg-sky-500 px-3 py-2 text-sm font-medium text-slate-100 transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50";
  const variants: Record<Variant, string> = {
    primary: "",
    secondary: "",
    danger: "",
    ghost: ""
  };
  return <button className={cx(base, variants[variant], className)} {...props} />;
}
