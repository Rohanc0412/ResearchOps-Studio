import { Card } from "../ui/Card";

export function BudgetPanel({ budgets }: { budgets?: Record<string, unknown> | null }) {
  return (
    <Card>
      <div className="mb-2 text-sm font-semibold text-slate-100">Budgets</div>
      {!budgets ? (
        <div className="text-sm text-slate-500">No budget data available.</div>
      ) : (
        <pre className="overflow-auto rounded-md border border-slate-900 bg-black/30 p-3 text-xs text-slate-300">
          {JSON.stringify(budgets, null, 2)}
        </pre>
      )}
    </Card>
  );
}

