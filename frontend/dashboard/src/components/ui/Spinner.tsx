import { cx } from "../../utils/format";

type SpinnerSize = "sm" | "md";

const sizeClasses: Record<SpinnerSize, string> = {
  sm: "h-4 w-4 border-2",
  md: "h-5 w-5 border-2",
};

export function Spinner({
  size = "md",
  label,
}: {
  size?: SpinnerSize;
  label?: string;
}) {
  return (
    <div className="inline-flex flex-col items-center gap-2">
      <span
        className={cx(
          "animate-spin rounded-full border-obsidian-border border-t-obsidian-accent",
          sizeClasses[size]
        )}
        role="status"
        aria-label={label ?? "Loading"}
      />
      {label && (
        <span className="text-xs font-sans text-obsidian-muted">{label}</span>
      )}
    </div>
  );
}
