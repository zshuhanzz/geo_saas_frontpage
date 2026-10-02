import type { StaticReportSnapshot } from "@/lib/api";

export type SnapshotRow = Record<string, any>;

export function formatDate(value?: string | null): string {
  if (!value) return "-";
  const d = new Date(value.includes("T") ? value : `${value}T00:00:00`);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function formatDateTime(value?: string | null): string {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString();
}

export function formatNumber(value: any, digits = 0): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return n.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits > 0 ? 0 : undefined,
  });
}

export function formatPercent(value: any): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${formatNumber(n, 1)}%`;
}

export function rowMatchesQuery(row: SnapshotRow, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return Object.values(row).some((value) => String(value ?? "").toLowerCase().includes(needle));
}

export function filterRowsByDate(rows: SnapshotRow[] = [], date: string): SnapshotRow[] {
  if (date === "all") return rows;
  return rows.filter((row) => String(row.date || row.executed_at || "").slice(0, 10) === date);
}

export function rowsForDate(
  aggregateRows: SnapshotRow[] = [],
  dailyRows: SnapshotRow[] = [],
  date: string,
): SnapshotRow[] {
  if (date === "all") return aggregateRows;
  return filterRowsByDate(dailyRows, date);
}

export function getAvailableDates(snapshot: StaticReportSnapshot): string[] {
  const explicit = (snapshot.report as any).available_dates;
  if (Array.isArray(explicit) && explicit.length > 0) {
    return explicit.map(String).sort();
  }

  const dates = new Set<string>();
  const collect = (rows?: SnapshotRow[]) =>
    rows?.forEach((row) => {
      const date = String(row.date || row.executed_at || "").slice(0, 10);
      if (/^\d{4}-\d{2}-\d{2}$/.test(date)) dates.add(date);
    });
  collect(snapshot.visibility?.time_series as SnapshotRow[]);
  collect(snapshot.visibility?.ranking_by_day as SnapshotRow[]);
  collect(snapshot.citations?.domains_by_day as SnapshotRow[]);
  collect(snapshot.sentiment?.summary_by_day as SnapshotRow[]);
  return Array.from(dates).sort();
}

export function sumRows(rows: SnapshotRow[], key: string): number {
  return rows.reduce((total, row) => {
    const n = Number(row[key]);
    return total + (Number.isFinite(n) ? n : 0);
  }, 0);
}
