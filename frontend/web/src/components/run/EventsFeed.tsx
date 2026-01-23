import { useEffect, useMemo, useRef } from "react";
import { ChevronDown } from "lucide-react";

import type { RunEvent } from "../../types/dto";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { cx, formatTs } from "../../utils/format";

export function EventsFeed({
  events,
  autoScroll,
  onToggleAutoScroll
}: {
  events: RunEvent[];
  autoScroll: boolean;
  onToggleAutoScroll: () => void;
}) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!autoScroll) return;
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [autoScroll, events.length]);

  const rows = useMemo(() => events.slice(-500), [events]);

  return (
    <Card className="p-0">
      <div className="flex items-center justify-between border-b border-slate-900 px-4 py-3">
        <div className="text-sm font-semibold text-slate-100">Live Events</div>
        <Button variant="secondary" onClick={onToggleAutoScroll}>
          <ChevronDown className="h-4 w-4" />
          {autoScroll ? "Auto-scroll on" : "Auto-scroll off"}
        </Button>
      </div>
      <div className="max-h-[420px] overflow-auto px-4 py-3">
        {rows.length === 0 ? <div className="text-sm text-slate-500">No events yet.</div> : null}
        <div className="flex flex-col gap-2">
          {rows.map((e, idx) => (
            <div key={`${e.ts}-${idx}`} className="rounded-lg border border-slate-900 bg-slate-950 px-3 py-2">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Badge tone={toneFromLevel(e.level)}>{e.level}</Badge>
                  <span className="text-xs text-slate-500">{formatTs(e.ts)}</span>
                  <span className="text-xs text-slate-400">{e.stage}</span>
                </div>
              </div>
              <div className={cx("mt-1 text-sm text-slate-100", e.level === "error" && "text-rose-100")}>
                {e.message}
              </div>
              {e.payload ? (
                <pre className="mt-2 overflow-auto rounded-md border border-slate-900 bg-black/30 p-2 text-xs text-slate-300">
                  {JSON.stringify(e.payload, null, 2)}
                </pre>
              ) : null}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </div>
    </Card>
  );
}

function toneFromLevel(level: RunEvent["level"]): "info" | "warning" | "danger" {
  if (level === "warn") return "warning";
  if (level === "error") return "danger";
  return "info";
}

