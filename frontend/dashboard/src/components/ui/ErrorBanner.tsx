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
        "flex items-start gap-3 rounded-lg px-4 py-3",
        className
      )}
      role="alert"
      style={{ backgroundColor: "#2a1515", border: "1px solid #5a2020" }}
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" aria-hidden="true" />
      <div className="space-y-0.5">
        <p className="text-sm font-medium font-sans text-red-400">{title}</p>
        <p className="text-sm font-sans" style={{ color: "#f87171" }}>{message}</p>
      </div>
    </div>
  );
}
