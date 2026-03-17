export function formatTs(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

export function cx(...classes: Array<string | undefined | null | false>): string {
  return classes.filter(Boolean).join(" ");
}

