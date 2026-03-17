import { AlertTriangle } from "lucide-react";
import { cx } from "../../utils/format";

export function ErrorBanner({
  title = "Something went wrong",
  message,
  className
}: {
  title?: string;
  message: string;
  className?: string;
}) {
  return (
    <div className={cx("flex items-start gap-3 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-rose-100", className)}>
      <AlertTriangle className="mt-0.5 h-4 w-4 text-rose-200" />
      <div>
        <div className="text-sm font-semibold">{title}</div>
        <div className="text-sm text-rose-100/80">{message}</div>
      </div>
    </div>
  );
}

