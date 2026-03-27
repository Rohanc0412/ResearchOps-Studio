import { AlertCircle } from "lucide-react";
import { cx } from "../../utils/format";

export function ErrorBanner({
  title = "Something went wrong",
  message,
  className,
}: {
  title?: string;
  message: string;
  className?: string;
}) {
  return (
    <div
      className={cx(
        "flex items-start gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3",
        className
      )}
      role="alert"
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" aria-hidden="true" />
      <div className="space-y-0.5">
        <p className="text-sm font-medium font-sans text-red-400">{title}</p>
        <p className="text-sm font-sans text-red-400/80">{message}</p>
      </div>
    </div>
  );
}
