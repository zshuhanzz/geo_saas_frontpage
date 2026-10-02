import { Fragment, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { rowMatchesQuery, type SnapshotRow } from "./reportUtils";
import { SortableMetricHeader } from "@/components/ui/SortableMetricHeader";
import type { MetricSortDirection, MetricSortState } from "@/lib/metricSort";

export interface SnapshotColumn {
  key: string;
  label: string;
  className?: string;
  render?: (row: SnapshotRow) => ReactNode;
  metricKey?: string;
  defaultDirection?: MetricSortDirection;
}

export function SnapshotTable({
  rows,
  columns,
  getRowKey,
  expandable,
  initialLimit = 8,
  sort = null,
  onSortChange,
  sortingEnabled = false,
  sortListId,
  query: controlledQuery,
  onQueryChange,
}: {
  rows: SnapshotRow[];
  columns: SnapshotColumn[];
  getRowKey: (row: SnapshotRow, index: number) => string;
  expandable?: (row: SnapshotRow) => ReactNode;
  initialLimit?: number;
  sort?: MetricSortState | null;
  onSortChange?: (next: MetricSortState) => void;
  sortingEnabled?: boolean;
  sortListId?: string;
  query?: string;
  onQueryChange?: (value: string) => void;
}) {
  const { t } = useTranslation("reports");
  const [localQuery, setLocalQuery] = useState("");
  const query = controlledQuery ?? localQuery;
  const [showAll, setShowAll] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const filteredRows = useMemo(
    () => onQueryChange ? rows : rows.filter((row) => rowMatchesQuery(row, query)),
    [onQueryChange, rows, query],
  );
  const visibleRows = showAll ? filteredRows : filteredRows.slice(0, initialLimit);

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => onQueryChange ? onQueryChange(event.target.value) : setLocalQuery(event.target.value)}
            placeholder={t("detail.search")}
            className="h-9 pl-8"
          />
        </div>
        {filteredRows.length > initialLimit && (
          <Button variant="ghost" size="sm" onClick={() => setShowAll((value) => !value)}>
            {showAll ? t("detail.showLess") : t("detail.showAll")}
          </Button>
        )}
      </div>

      <div className="rounded-md border">
        <Table data-sort-list={sortListId}>
          <TableHeader>
            <TableRow>
              {expandable && <TableHead className="w-8" />}
              {columns.map((column) => (
                <TableHead key={column.key} className={column.className}>
                  {sortingEnabled && column.metricKey && sort && onSortChange ? (
                    <SortableMetricHeader
                      label={column.label}
                      metricKey={column.metricKey}
                      sort={sort}
                      onChange={onSortChange}
                      defaultDirection={column.defaultDirection}
                    />
                  ) : column.label}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {visibleRows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns.length + (expandable ? 1 : 0)} className="h-24 text-center text-muted-foreground">
                  {t("detail.noRows")}
                </TableCell>
              </TableRow>
            ) : (
              visibleRows.map((row, index) => {
                const key = getRowKey(row, index);
                const isExpanded = Boolean(expanded[key]);
                return (
                  <Fragment key={key}>
                    <TableRow key={key}>
                      {expandable && (
                        <TableCell className="w-8">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            onClick={() => setExpanded((prev) => ({ ...prev, [key]: !prev[key] }))}
                          >
                            {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                          </Button>
                        </TableCell>
                      )}
                      {columns.map((column) => (
                        <TableCell key={column.key} className={cn("align-top", column.className)}>
                          {column.render ? column.render(row) : String(row[column.key] ?? "-")}
                        </TableCell>
                      ))}
                    </TableRow>
                    {expandable && isExpanded && (
                      <TableRow key={`${key}-expanded`} className="bg-muted/20 hover:bg-muted/20">
                        <TableCell colSpan={columns.length + 1} className="p-4 text-sm text-muted-foreground">
                          {expandable(row)}
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
