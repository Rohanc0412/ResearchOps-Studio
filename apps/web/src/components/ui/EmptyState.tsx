import { Card } from "./Card";

export function EmptyState({
  title,
  description,
  action
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <Card className="flex flex-col gap-2">
      <div className="text-sm font-semibold text-slate-100">{title}</div>
      {description ? <div className="text-sm text-slate-400">{description}</div> : null}
      {action ? <div className="pt-2">{action}</div> : null}
    </Card>
  );
}

