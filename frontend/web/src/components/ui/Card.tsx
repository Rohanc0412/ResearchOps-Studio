import { cx } from "../../utils/format";

export function Card({
  className,
  children
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return <div className={cx("rounded-xl border border-slate-800 bg-slate-950/50 p-4 shadow-soft", className)}>{children}</div>;
}

