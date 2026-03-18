export function CitationBadge({ number }: { number: number }) {
  return (
    <span className="ml-1.5 inline-flex items-center justify-center rounded bg-emerald-500/15 px-2 py-0.5 font-mono text-xs font-semibold text-emerald-400">
      [{number}]
    </span>
  );
}
