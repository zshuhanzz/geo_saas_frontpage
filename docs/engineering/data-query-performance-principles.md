# Data Query Performance Principles

Last updated: 2026-06-20

This note captures the performance lessons from the Overview, Visibility, Citation, Sentiment, and Static Report optimization pass.

## Operating Context

- Primary database: Cloud SQL PostgreSQL, currently 2 vCPU / 16 GB.
- Data pattern: GEO Collector and GEO Analyzer update analytics data in daily batches. Most dashboard data is read-heavy and changes once per day per client.
- High-risk tables: response-level results, brand mentions, citations, and static report snapshots.
- High-risk pages: Overview, Visibility, Citation, Sentiment, and Static Reports because they can fan out into many chart and list queries.

## Non-Negotiable Query Rules

1. Always push aggregation to SQL.
   Dashboard APIs should return aggregated metrics, chart points, or paginated short lists. Do not pull large detail rows into application memory and aggregate in Python.

2. Lists must be paginated at SQL level.
   Use `ORDER BY ... LIMIT ... OFFSET` or keyset pagination. Do not fetch the full ranking and slice the first 20 or 50 rows in memory.

3. Snapshot reports must not store full source-row payloads by default.
   Static reports should store summary/chart data and first-page list rows only. Detail pages may fetch later pages from live paginated APIs.

4. Distinguish interactive HTML from exported HTML.
   Interactive report pages can fetch later pages live. Exported HTML should preserve first-page data and should not promise live pagination.

5. Avoid duplicated full-table scans from one page load.
   A page like Overview must use purpose-built lightweight SQL. It must not simply call heavy Visibility, Citation, and Sentiment endpoints repeatedly.

6. Treat multi-select filters as load multipliers.
   Topic/platform filters can increase query cost and frontend request fan-out. Test multi-topic and all-topic cases, not only single-topic happy paths.

7. Never let stale frontend responses overwrite newer filter state.
   For filter-driven pages, use `AbortController` plus a request sequence guard. Aborting alone is not enough because an in-flight request may already have reached the server.

8. Be careful with React effect dependencies.
   Do not put freshly created arrays/objects into request effect dependency lists. Use stable constants, memoized keys, and scalar dependencies to avoid cancel/re-request loops.

9. Add database timeouts by default.
   All SaaS API DB work should run with statement/query timeout and pool acquire timeout. A slow query should fail fast instead of occupying a connection for minutes.

10. Connection pools protect the database, they do not make slow SQL fast.
    Per-instance pool size should stay conservative. More connections can increase database CPU contention if SQL remains expensive.

## Current Pool Guidance

- Current SaaS API pool max size: 8 connections per Cloud Run instance.
- Current DB statement/query timeout: 60 seconds.
- Current pool acquire timeout: 10 seconds.
- For a 2 vCPU Cloud SQL instance, pool size 8 is intentionally conservative but still not tiny. It caps concurrency so one Cloud Run instance cannot open too many simultaneous database queries.
- If Cloud SQL is upgraded to 4 vCPU, consider testing pool max 10-12 only after slow SQL is reduced. Do not raise pool size as a substitute for SQL optimization.

## Static Report Rules

- Materialize should store:
  - report metadata
  - filter options
  - summary metrics
  - chart series
  - first-page rows for important lists
- Materialize should not store:
  - full citation source rows
  - full visibility response source rows
  - full page/domain rankings beyond the first page unless there is a clear product reason
- Static report detail APIs should be split by section so the page can load progressively.
- Section filters should call the same split dynamic endpoints as the live dashboards.
- Later pages for cited domains, cited pages, and published URL tracking should be fetched from live paginated APIs.

## Frontend Request Rules

- On filter changes, cancel prior requests with `AbortController`.
- Add request sequence guards before writing state from async responses.
- Preserve already-rendered data unless the user clearly changed the query scope.
- For list pagination, loading the next page should not clear unrelated sections.
- In React effects, avoid dependencies such as `rows || []` that create a new array every render.

## Monitoring Checklist

After deploying query-heavy changes, inspect:

- Cloud Run latency buckets: especially requests over 30s, 50s, and 60s.
- Cloud Run 5xx count and endpoint names.
- Cloud SQL CPU utilization:
  - sustained >50% means watch closely
  - repeated spikes to 100% mean immediate query/concurrency review
- Cloud SQL memory utilization.
- Cloud SQL connections.
- Cloud SQL read/write IO.

## Future Optimization Backlog

- Consider daily pre-aggregation tables for high-cardinality Citation and Visibility views.
- Consider BigQuery or another OLAP path for historical analytical queries if row volume continues to grow.
- Add per-endpoint slow query logging with SQL stage timing in API logs.
- Add dashboard-level load tests for one, two, and three simultaneous tabs.
- Add alerts for Cloud SQL CPU saturation and Cloud Run 5xx bursts.
