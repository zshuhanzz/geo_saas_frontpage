export type PromptDrilldownRouteTarget =
  | { kind: "topic"; topicId: string }
  | { kind: "product"; topicId: string; product: string }
  | { kind: "prompt"; promptId: string };

export interface PromptConceptTarget {
  topic_id: string;
  product: string | null;
  prompt_ids: string[];
}

export interface PromptDrilldownCommonFilters {
  dateFrom: string;
  dateTo: string;
  interval: string;
  topicIds: string[];
  platforms: string[];
  countries: string[];
  promptTypes: string[];
}

export interface PromptDrilldownResolvedFilters extends PromptDrilldownCommonFilters {
  products?: string[];
  promptIds?: string[];
  emptyIntersection?: boolean;
}

const BASE_PATH = "/insights/prompts";

export function selectDashboardFilterKey(
  mode: "sidebar" | "drilldown",
  rawFilterKey: string,
  debouncedFilterKey: string,
  ownershipChanged = false,
): string {
  return mode === "drilldown" || ownershipChanged ? rawFilterKey : debouncedFilterKey;
}

function clean(value: string | null | undefined): string {
  return value?.trim() ?? "";
}

function cleanPathPart(value: string | undefined): string {
  if (!value) return "";
  try {
    return clean(decodeURIComponent(value));
  } catch {
    return "";
  }
}

export function buildTopicDrilldownHref(topicId: string): string | null {
  const id = clean(topicId);
  return id ? `${BASE_PATH}/topic/${encodeURIComponent(id)}` : null;
}

export function buildProductDrilldownHref(topicId: string, product: string): string | null {
  const id = clean(topicId);
  const label = clean(product);
  if (!id || !label) return null;
  const query = new URLSearchParams({ topic_id: id, product: label });
  return `${BASE_PATH}/product?${query.toString()}`;
}

export function buildPromptDrilldownHref(promptId: string): string | null {
  const id = clean(promptId);
  return id ? `${BASE_PATH}/prompt/${encodeURIComponent(id)}` : null;
}

export function parsePromptDrilldownLocation(
  pathname: string,
  search: string,
): PromptDrilldownRouteTarget | null {
  const suffix = pathname.startsWith(BASE_PATH) ? pathname.slice(BASE_PATH.length) : pathname;
  const parts = suffix.split("/").filter(Boolean);
  if (parts[0] === "topic" && parts.length === 2) {
    const topicId = cleanPathPart(parts[1]);
    return topicId ? { kind: "topic", topicId } : null;
  }
  if (parts[0] === "prompt" && parts.length === 2) {
    const promptId = cleanPathPart(parts[1]);
    return promptId ? { kind: "prompt", promptId } : null;
  }
  if (parts[0] === "product" && parts.length === 1) {
    const query = new URLSearchParams(search);
    const topicId = clean(query.get("topic_id"));
    const product = clean(query.get("product"));
    return topicId && product ? { kind: "product", topicId, product } : null;
  }
  return null;
}

function isTopicAllowed(globalTopicIds: string[], targetTopicId: string): boolean {
  return globalTopicIds.length === 0 || globalTopicIds.includes(targetTopicId);
}

export function resolvePromptDrilldownFilters(
  common: PromptDrilldownCommonFilters,
  target: PromptDrilldownRouteTarget,
  concept?: PromptConceptTarget,
): PromptDrilldownResolvedFilters {
  const snapshot: PromptDrilldownResolvedFilters = {
    ...common,
    topicIds: [...common.topicIds],
    platforms: [...common.platforms],
    countries: [...common.countries],
    promptTypes: [...common.promptTypes],
  };

  if (target.kind === "topic") {
    return { ...snapshot, topicIds: [target.topicId] };
  }
  if (target.kind === "product") {
    if (!isTopicAllowed(common.topicIds, target.topicId)) return { ...snapshot, emptyIntersection: true };
    return { ...snapshot, topicIds: [target.topicId], products: [target.product] };
  }
  if (!concept || concept.prompt_ids.length === 0 || !clean(concept.topic_id)) {
    return { ...snapshot, emptyIntersection: true };
  }
  if (!isTopicAllowed(common.topicIds, concept.topic_id)) return { ...snapshot, emptyIntersection: true };
  return {
    ...snapshot,
    topicIds: [concept.topic_id],
    ...(clean(concept.product) ? { products: [clean(concept.product)] } : {}),
    promptIds: [...concept.prompt_ids],
  };
}
