import { cx } from "../../utils/format";

export function Badge({
  tone = "neutral",
  className,
  children
}: {
  tone?: "neutral" | "success" | "warning" | "danger" | "info";
  className?: string;
  children: React.ReactNode;
}) {
  const tones: Record<string, string> = {
    neutral: "bg-slate-800 text-slate-200",
    info: "bg-sky-500/15 text-sky-200 ring-1 ring-sky-500/30",
    success: "bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-500/30",
    warning: "bg-amber-500/15 text-amber-200 ring-1 ring-amber-500/30",
    danger: "bg-rose-500/15 text-rose-200 ring-1 ring-rose-500/30"
  };
  return (
    <span className={cx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", tones[tone], className)}>
      {children}
    </span>
  );
}

