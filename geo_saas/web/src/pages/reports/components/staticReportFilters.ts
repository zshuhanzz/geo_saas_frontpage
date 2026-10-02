import type { StaticReportSnapshot } from "@/lib/api";

export interface StaticReportFilterState {
  topicIds: string[];
  platforms: string[];
}

function round(value: number, digits = 1): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

const CITATION_DISPLAY_LIMIT = 50;

function hasFilters(filters: StaticReportFilterState): boolean {
  return filters.topicIds.length > 0 || filters.platforms.length > 0;
}

function rowMatches(row: any, filters: StaticReportFilterState): boolean {
  const topicId = String(row.topic_id || "");
  const platform = String(row.platform || "");
  return (
    (filters.topicIds.length === 0 || filters.topicIds.includes(topicId)) &&
    (filters.platforms.length === 0 || filters.platforms.includes(platform))
  );
}

function visibilityBucketKey(row: any): string {
  return [
    row.date || "",
    row.topic_id || "",
    row.prompt_id || "",
    row.platform || "",
    row.product || "",
  ].join("|");
}

function buildDateKeys(report: StaticReportSnapshot["report"]): string[] {
  const start = report?.window_start;
  const end = report?.window_end;
  if (!start || !end) return [];
  const values: string[] = [];
  const current = new Date(`${start}T00:00:00`);
  const last = new Date(`${end}T00:00:00`);
  while (current <= last) {
    const year = current.getFullYear();
    const month = String(current.getMonth() + 1).padStart(2, "0");
    const day = String(current.getDate()).padStart(2, "0");
    values.push(`${year}-${month}-${day}`);
    current.setDate(current.getDate() + 1);
  }
  return values;
}

function rankRows<T extends Record<string, any>>(rows: T[], valueKey: string, ascending = false): Array<T & { rank: number }> {
  return [...rows]
    .sort((a, b) => {
      const av = Number(a[valueKey] ?? 0);
      const bv = Number(b[valueKey] ?? 0);
      if (av !== bv) return ascending ? av - bv : bv - av;
      return String(a.brand_name || a.company_name || a.domain || a.url || a.theme_name || "").localeCompare(
        String(b.brand_name || b.company_name || b.domain || b.url || b.theme_name || ""),
      );
    })
    .map((row, index) => ({ ...row, rank: index + 1 }));
}

function aggregateVisibility(dashboard: any, filters: StaticReportFilterState, report: StaticReportSnapshot["report"]): any {
  if (dashboard?.source_rows_limited || dashboard?.response_source_rows_limited) return dashboard;
  const rows = (dashboard?.source_rows || []).filter((row: any) => rowMatches(row, filters));
  const responseRows = (dashboard?.response_source_rows || []).filter((row: any) => rowMatches(row, filters));
  const dateKeys = buildDateKeys(report);
  if (!rows.length && !responseRows.length) {
    return {
      ...dashboard,
      summary: {
        visibility_score: 0,
        visibility_rank: null,
        mentioned: 0,
        total_query: 0,
        sov_pct: 0,
        sov_rank: null,
        total_mentions: 0,
        own_mentions: 0,
        avg_position: null,
        avg_position_rank: null,
      },
      sov_ranking: [],
      visibility_ranking: [],
      position_ranking: [],
      topic_sov_ranking: [],
      product_sov_ranking: [],
      time_series: dateKeys.map((date) => ({ date, score: 0, total: 0, own_count: 0 })),
      avg_position_series: dateKeys.map((date) => ({ date, avg_position: null })),
    };
  }

  const responseBucketMap = new Map<string, any>();
  for (const row of responseRows) {
    responseBucketMap.set(visibilityBucketKey(row), row);
  }
  const totalResponses = responseBucketMap.size > 0
    ? Array.from(responseBucketMap.values()).reduce((sum, row) => sum + Number(row.total_response_count || 0), 0)
    : rows.reduce((sum: number, row: any) => sum + Number(row.total_response_count || 0), 0);

  const brandMap = new Map<string, any>();
  for (const row of rows) {
    const name = row.company_name || row.brand_name || "(unknown)";
    const count = Number(row.mention_count || 0);
    const responseCount = Number(row.response_count ?? row.brand_response_count ?? count);
    const avg = row.avg_position == null ? null : Number(row.avg_position);
    const entry = brandMap.get(name) || {
      brand_name: name,
      company_name: name,
      mention_count: 0,
      response_count: 0,
      weighted_position: 0,
      position_count: 0,
      is_own: false,
    };
    entry.mention_count += count;
    entry.response_count += responseCount;
    entry.is_own = entry.is_own || Boolean(row.is_own);
    if (avg != null) {
      entry.weighted_position += avg * count;
      entry.position_count += count;
    }
    brandMap.set(name, entry);
  }

  const totalMentions = rows.reduce((sum: number, row: any) => sum + Number(row.mention_count || 0), 0);
  const visibilityDenominator = totalResponses;
  const entries = Array.from(brandMap.values()).map((entry) => ({
    ...entry,
    avg_position: entry.position_count > 0 ? round(entry.weighted_position / entry.position_count, 2) : null,
    sov_pct: totalMentions > 0 ? round((entry.mention_count / totalMentions) * 100, 2) : 0,
    visibility_pct: visibilityDenominator > 0 ? round((entry.response_count / visibilityDenominator) * 100, 2) : 0,
  }));
  const sovRanking = rankRows(entries, "mention_count");
  const visibilityRanking = rankRows(entries, "visibility_pct");
  const positionRanking = rankRows(entries.filter((row) => row.avg_position != null), "avg_position", true);
  const ownRow = sovRanking.find((row) => row.is_own);
  const ownPositionRow = positionRanking.find((row) => row.is_own);
  const byDate = new Map<string, { total: number; own: number; weightedPosition: number; positionCount: number }>();
  if (responseBucketMap.size > 0) {
    for (const row of responseBucketMap.values()) {
      const date = String(row.date || "");
      if (!date) continue;
      const entry = byDate.get(date) || { total: 0, own: 0, weightedPosition: 0, positionCount: 0 };
      entry.total += Number(row.total_response_count || 0);
      entry.own += Number(row.own_response_count || 0);
      byDate.set(date, entry);
    }
  }
  for (const row of rows) {
    const date = String(row.date || "");
    if (!date) continue;
    const count = Number(row.mention_count || 0);
    const entry = byDate.get(date) || { total: 0, own: 0, weightedPosition: 0, positionCount: 0 };
    if (responseBucketMap.size === 0) entry.total += count;
    if (row.is_own) {
      if (responseBucketMap.size === 0) entry.own += count;
      const avg = row.avg_position == null ? null : Number(row.avg_position);
      if (avg != null) {
        entry.weightedPosition += avg * count;
        entry.positionCount += count;
      }
    }
    byDate.set(date, entry);
  }
  const trendDates = dateKeys.length > 0 ? dateKeys : Array.from(byDate.keys()).sort((a, b) => a.localeCompare(b));
  const timeSeries = trendDates
    .map((date) => {
      const row = byDate.get(date) || { total: 0, own: 0 };
      return {
      date,
      score: row.total > 0 ? round((row.own / row.total) * 100, 2) : null,
      total: row.total,
      own_count: row.own,
      };
    });
  const avgPositionSeries = trendDates
    .map((date) => {
      const row = byDate.get(date);
      return {
      date,
      avg_position: row && row.positionCount > 0 ? round(row.weightedPosition / row.positionCount, 2) : null,
      };
    });

  return {
    ...dashboard,
    summary: {
      ...dashboard.summary,
      visibility_score: ownRow?.visibility_pct ?? 0,
      visibility_rank: visibilityRanking.find((row) => row.is_own)?.rank ?? null,
      mentioned: ownRow?.response_count ?? ownRow?.mention_count ?? 0,
      total_query: visibilityDenominator,
      sov_pct: ownRow?.sov_pct ?? 0,
      sov_rank: ownRow?.rank ?? null,
      total_mentions: totalMentions,
      own_mentions: ownRow?.mention_count ?? 0,
      avg_position: ownPositionRow?.avg_position ?? null,
      avg_position_rank: ownPositionRow?.rank ?? null,
    },
    sov_ranking: sovRanking,
    visibility_ranking: visibilityRanking,
    position_ranking: positionRanking,
    time_series: timeSeries,
    avg_position_series: avgPositionSeries,
    topic_sov_ranking: (dashboard.topic_sov_ranking || []).filter((row: any) => {
      if (filters.topicIds.length === 0) return true;
      return filters.topicIds.includes(String(row.topic_id || ""));
    }),
    product_sov_ranking: dashboard.product_sov_ranking || [],
  };
}

function aggregateCitations(dashboard: any, filters: StaticReportFilterState, report: StaticReportSnapshot["report"]): any {
  if (dashboard?.source_rows_limited) return dashboard;
  const rows = (dashboard?.source_rows || []).filter((row: any) => rowMatches(row, filters));
  const dateKeys = buildDateKeys(report);
  if (!rows.length) {
    return {
      ...dashboard,
      summary: { total_citations: 0, own_domain_share: 0, own_citation_count: 0, own_rank: null },
      domain_ranking: [],
      page_ranking: [],
      category_breakdown: [],
      time_series: dateKeys.map((date) => ({ date, own_share: null, total_citations: 0, own_citations: 0 })),
    };
  }

  const ownDomains = new Set(
    ((dashboard.own_domains || []).length > 0
      ? dashboard.own_domains
      : (dashboard.domain_ranking || []).filter((row: any) => row.is_own).map((row: any) => row.domain)
    ).map((domain: any) => String(domain || "").toLowerCase()),
  );
  const total = rows.reduce((sum: number, row: any) => sum + Number(row.citation_count || 0), 0);
  const domainMap = new Map<string, any>();
  const pageMap = new Map<string, any>();
  const categoryMap = new Map<string, number>();
  const dateMap = new Map<string, { total: number; own: number }>();

  for (const row of rows) {
    const count = Number(row.citation_count || 0);
    const domain = row.source_domain || "(unknown)";
    const category = row.domain_category || "Other";
    const isOwn = ownDomains.has(String(domain || "").toLowerCase());
    const domainEntry = domainMap.get(domain) || { domain, citation_count: 0, domain_category: category };
    domainEntry.citation_count += count;
    domainMap.set(domain, domainEntry);
    if (row.source_url) {
      const pageEntry = pageMap.get(row.source_url) || { url: row.source_url, domain, citation_count: 0, domain_category: category };
      pageEntry.citation_count += count;
      pageMap.set(row.source_url, pageEntry);
    }
    categoryMap.set(category, (categoryMap.get(category) || 0) + count);
    const date = String(row.date || "");
    if (date) {
      const dateEntry = dateMap.get(date) || { total: 0, own: 0 };
      dateEntry.total += count;
      if (isOwn) dateEntry.own += count;
      dateMap.set(date, dateEntry);
    }
  }

  const fullDomainRanking = rankRows(
    Array.from(domainMap.values()).map((row) => ({
      ...row,
      share_pct: total > 0 ? round((row.citation_count / total) * 100, 2) : 0,
      is_own: ownDomains.has(String(row.domain || "").toLowerCase()),
    })),
    "citation_count",
  );
  const fullPageRanking = rankRows(
    Array.from(pageMap.values()).map((row) => ({
      ...row,
      share_pct: total > 0 ? round((row.citation_count / total) * 100, 2) : 0,
      is_own: ownDomains.has(String(row.domain || "").toLowerCase()),
    })),
    "citation_count",
  );
  const ownCitationCount = fullDomainRanking.filter((row) => row.is_own).reduce((sum, row) => sum + Number(row.citation_count || 0), 0);
  const trendDates = dateKeys.length > 0 ? dateKeys : Array.from(dateMap.keys()).sort((a, b) => a.localeCompare(b));
  const timeSeries = trendDates
    .map((date) => {
      const row = dateMap.get(date) || { total: 0, own: 0 };
      return {
      date,
      own_share: row.total > 0 ? round((row.own / row.total) * 100, 2) : null,
      total_citations: row.total,
      own_citations: row.own,
      };
    });

  return {
    ...dashboard,
    summary: {
      ...dashboard.summary,
      total_citations: total,
      own_domain_share: total > 0 ? round((ownCitationCount / total) * 100, 2) : 0,
      own_citation_count: ownCitationCount,
      own_rank: fullDomainRanking.find((row) => row.is_own)?.rank ?? null,
    },
    domain_ranking: fullDomainRanking.slice(0, CITATION_DISPLAY_LIMIT),
    page_ranking: fullPageRanking.slice(0, CITATION_DISPLAY_LIMIT),
    time_series: timeSeries,
    category_breakdown: Array.from(categoryMap.entries()).map(([label, count]) => ({
      label,
      count,
      pct: total > 0 ? round((count / total) * 100, 2) : 0,
    })),
  };
}

function aggregateSentiment(dashboard: any, filters: StaticReportFilterState, report: StaticReportSnapshot["report"]): any {
  if (dashboard?.source_rows_limited || dashboard?.response_source_rows_limited) return dashboard;
  if (!Array.isArray(dashboard?.response_source_rows)) return dashboard;
  const rows = (dashboard?.source_rows || []).filter((row: any) => rowMatches(row, filters));
  const responseRows = dashboard.response_source_rows.filter((row: any) => rowMatches(row, filters));
  const examples = (dashboard?.examples || []).filter((row: any) => rowMatches(row, filters));
  const dateKeys = buildDateKeys(report);
  if (!responseRows.length) {
    return {
      ...dashboard,
      summary: {
        positive_pct: 0,
        mixed_neutral_pct: 0,
        negative_pct: 0,
        positive_count: 0,
        mixed_neutral_count: 0,
        negative_count: 0,
        insufficient_evidence_count: 0,
        rated_count: 0,
        total_count: 0,
        positive_top3_themes: [],
        negative_top3_themes: [],
      },
      time_series: dateKeys.map((date) => ({
        date,
        positive_pct: null,
        mixed_neutral_pct: null,
        negative_pct: null,
        positive: 0,
        mixed_neutral: 0,
        negative: 0,
        insufficient_evidence: 0,
        rated: 0,
        total: 0,
      })),
      themes: [],
      examples: [],
    };
  }
  const countFor = (sentiment: string) => responseRows
    .filter((row: any) => row.sentiment === sentiment)
    .reduce((sum: number, row: any) => sum + Number(row.count || 0), 0);
  const positive = countFor("Positive");
  const mixedNeutral = countFor("Mixed/Neutral");
  const negative = countFor("Negative");
  const insufficientEvidence = countFor("Insufficient Evidence");
  const rated = positive + mixedNeutral + negative;
  const total = rated + insufficientEvidence;
  const dateMap = new Map<string, { rated: number; total: number; positive: number; mixedNeutral: number; negative: number; insufficientEvidence: number }>();
  for (const row of responseRows) {
    const date = String(row.date || "");
    if (!date) continue;
    const count = Number(row.count || 0);
    const entry = dateMap.get(date) || {
      rated: 0, total: 0, positive: 0, mixedNeutral: 0, negative: 0, insufficientEvidence: 0,
    };
    entry.total += count;
    if (row.sentiment === "Positive") { entry.positive += count; entry.rated += count; }
    if (row.sentiment === "Mixed/Neutral") { entry.mixedNeutral += count; entry.rated += count; }
    if (row.sentiment === "Negative") { entry.negative += count; entry.rated += count; }
    if (row.sentiment === "Insufficient Evidence") entry.insufficientEvidence += count;
    dateMap.set(date, entry);
  }
  const trendDates = dateKeys.length > 0 ? dateKeys : Array.from(dateMap.keys()).sort((a, b) => a.localeCompare(b));
  const timeSeries = trendDates
    .map((date) => {
      const row = dateMap.get(date) || {
        rated: 0, total: 0, positive: 0, mixedNeutral: 0, negative: 0, insufficientEvidence: 0,
      };
      return {
      date,
      positive_pct: row.rated > 0 ? round((row.positive / row.rated) * 100, 2) : null,
      mixed_neutral_pct: row.rated > 0 ? round((row.mixedNeutral / row.rated) * 100, 2) : null,
      negative_pct: row.rated > 0 ? round((row.negative / row.rated) * 100, 2) : null,
      positive: row.positive,
      mixed_neutral: row.mixedNeutral,
      negative: row.negative,
      insufficient_evidence: row.insufficientEvidence,
      rated: row.rated,
      total: row.total,
      };
    });
  const themes = rankRows(
    rows.map((row: any) => ({
      theme_name: row.theme_name,
      sentiment: row.sentiment,
      occurrence_count: Number(row.occurrence_count || 0),
      occurrence_change: null,
      prev_occurrence_count: 0,
    })),
    "occurrence_count",
  );
  return {
    ...dashboard,
    summary: {
      ...dashboard.summary,
      positive_pct: rated > 0 ? round((positive / rated) * 100, 2) : 0,
      mixed_neutral_pct: rated > 0 ? round((mixedNeutral / rated) * 100, 2) : 0,
      negative_pct: rated > 0 ? round((negative / rated) * 100, 2) : 0,
      positive_count: positive,
      mixed_neutral_count: mixedNeutral,
      negative_count: negative,
      insufficient_evidence_count: insufficientEvidence,
      rated_count: rated,
      total_count: total,
      positive_top3_themes: themes.filter((row) => row.sentiment === "Positive").slice(0, 3).map((row) => row.theme_name),
      negative_top3_themes: themes.filter((row) => row.sentiment === "Negative").slice(0, 3).map((row) => row.theme_name),
    },
    time_series: timeSeries,
    themes,
    examples,
  };
}

export function applyStaticReportFilters(snapshot: StaticReportSnapshot, filters: StaticReportFilterState): StaticReportSnapshot {
  if (!hasFilters(filters)) return snapshot;
  return {
    ...snapshot,
    visibility: {
      ...snapshot.visibility,
      dashboard: aggregateVisibility(snapshot.visibility?.dashboard || {}, filters, snapshot.report),
    },
    citations: {
      ...snapshot.citations,
      dashboard: aggregateCitations(snapshot.citations?.dashboard || {}, filters, snapshot.report),
    },
    sentiment: {
      ...snapshot.sentiment,
      dashboard: aggregateSentiment(snapshot.sentiment?.dashboard || {}, filters, snapshot.report),
    },
  };
}
