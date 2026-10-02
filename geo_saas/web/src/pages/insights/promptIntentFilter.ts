export interface IntentFacets {
    active: string[];
    unconfigured: string[];
    has_unconfigured_blank: boolean;
}

export interface IntentFilterState {
    values: string[];
    includeBlank: boolean;
}

export type IntentFilterOption =
    | { kind: "value"; value: string }
    | { kind: "blank" };

export interface IntentOptionGroups {
    active: Array<{ kind: "value"; value: string }>;
    unconfigured: IntentFilterOption[];
}

export interface PromptListRow {
    client_id?: string | null;
    is_active?: boolean;
    topic_id?: string | null;
    product?: string | null;
    platform?: string | null;
    platforms?: readonly string[] | null;
    country?: string | null;
    countries?: readonly string[] | null;
    prompt_ids?: readonly string[] | null;
    variants?: ReadonlyArray<{ id: string; platform?: string | null; country?: string | null }> | null;
    text?: string | null;
    intent?: string | null;
    language?: string | null;
}

export interface PromptListFilters {
    activeOnly?: boolean;
    searchQuery?: string;
    topicId?: string | null;
    topicIds?: readonly string[];
    product?: string | null;
    platform?: string | null;
    platforms?: readonly string[];
    country?: string | null;
    countries?: readonly string[];
    intent: IntentFilterState;
}

export interface PromptVariantFilters {
    platform?: string | null;
    platforms?: readonly string[];
    country?: string | null;
    countries?: readonly string[];
}

export function selectPromptConceptVariants<Row extends PromptListRow>(
    row: Row,
    filters: PromptVariantFilters,
): Row | null {
    const variants = row.variants;
    if (!variants) return row;
    const selected = variants.filter((variant) => {
        const platform = variant.platform ?? "";
        const country = variant.country ?? "";
        if (filters.platform && platform !== filters.platform) return false;
        if (filters.platforms?.length && !filters.platforms.includes(platform)) return false;
        if (filters.country && country !== filters.country) return false;
        if (filters.countries?.length && !filters.countries.includes(country)) return false;
        return true;
    });
    if (selected.length === 0) return null;
    return {
        ...row,
        prompt_ids: selected.map((variant) => variant.id),
        variants: selected,
        platforms: Array.from(new Set(selected.map((variant) => variant.platform).filter((value): value is string => Boolean(value)))),
        countries: Array.from(new Set(selected.map((variant) => variant.country).filter((value): value is string => Boolean(value)))),
    };
}

function uniqueNonBlank(values: readonly string[]): string[] {
    return Array.from(new Set(values.filter((value) => value.trim().length > 0)));
}

export function buildIntentOptionGroups(facets: IntentFacets): IntentOptionGroups {
    const activeValues = uniqueNonBlank(facets.active);
    const activeSet = new Set(activeValues);
    const unconfiguredValues = uniqueNonBlank(facets.unconfigured)
        .filter((value) => !activeSet.has(value));

    return {
        active: activeValues.map((value) => ({ kind: "value", value })),
        unconfigured: [
            ...unconfiguredValues.map((value) => ({ kind: "value" as const, value })),
            ...(facets.has_unconfigured_blank ? [{ kind: "blank" as const }] : []),
        ],
    };
}

export function toggleIntentOption(
    state: IntentFilterState,
    option: IntentFilterOption,
): IntentFilterState {
    if (option.kind === "blank") {
        return { ...state, includeBlank: !state.includeBlank };
    }

    const selected = state.values.includes(option.value);
    return {
        ...state,
        values: selected
            ? state.values.filter((value) => value !== option.value)
            : [...state.values, option.value],
    };
}

export function matchesIntentFilter(
    intent: string | null | undefined,
    filter: IntentFilterState,
): boolean {
    if (filter.values.length === 0 && !filter.includeBlank) return true;
    if (intent == null || intent.trim().length === 0) return filter.includeBlank;
    const normalizedIntent = intent.trim().toLowerCase();
    return filter.values.some((value) => value.trim().toLowerCase() === normalizedIntent);
}

export function applyPromptListFilters<Row extends PromptListRow>(
    rows: readonly Row[],
    filters: PromptListFilters,
): Row[] {
    const query = filters.searchQuery?.trim().toLocaleLowerCase() ?? "";

    return rows.filter((row) => {
        if (filters.activeOnly && !row.is_active) return false;
        if (query) {
            const textMatches = row.text?.toLocaleLowerCase().includes(query) ?? false;
            const intentMatches = row.intent?.toLocaleLowerCase().includes(query) ?? false;
            if (!textMatches && !intentMatches) return false;
        }
        if (filters.topicId && row.topic_id !== filters.topicId) return false;
        if (filters.topicIds && filters.topicIds.length > 0 && !filters.topicIds.includes(row.topic_id ?? "")) return false;
        if (filters.product && row.product !== filters.product) return false;
        const rowPlatforms = row.platforms ?? (row.platform ? [row.platform] : []);
        const rowCountries = row.countries ?? (row.country ? [row.country] : []);
        if (filters.platform && !rowPlatforms.includes(filters.platform)) return false;
        if (filters.platforms && filters.platforms.length > 0 && !rowPlatforms.some((value) => filters.platforms!.includes(value))) return false;
        if (filters.country && !rowCountries.includes(filters.country)) return false;
        if (filters.countries && filters.countries.length > 0 && !rowCountries.some((value) => filters.countries!.includes(value))) return false;
        return matchesIntentFilter(row.intent, filters.intent);
    });
}

export type IntentWriteValidation = "missing" | "inactive" | null;

export function getIntentWriteValidation(
    intent: string | null | undefined,
    activeIntents: readonly string[],
): IntentWriteValidation {
    if (intent == null || intent.trim().length === 0) return "missing";
    return resolveCanonicalIntent(intent, activeIntents) ? null : "inactive";
}

export function resolveCanonicalIntent(
    intent: string | null | undefined,
    activeIntents: readonly string[],
): string | null {
    if (intent == null || intent.trim().length === 0) return null;
    const normalizedIntent = intent.trim().toLowerCase();
    const canonical = activeIntents.find(
        (activeIntent) => activeIntent.trim().toLowerCase() === normalizedIntent,
    );
    return canonical?.trim() || null;
}

export function isWorkspaceStateOwned(
    currentClientId: string | null | undefined,
    ownerClientId: string | null | undefined,
): boolean {
    return Boolean(currentClientId) && currentClientId === ownerClientId;
}

export function areSelectedCandidateIntentsActive(
    candidates: ReadonlyArray<{ selected: boolean; intent: string | null | undefined }>,
    activeIntents: readonly string[],
): boolean {
    return candidates
        .filter((candidate) => candidate.selected)
        .every((candidate) => getIntentWriteValidation(candidate.intent, activeIntents) === null);
}

export function buildLogicalPromptKey(
    row: PromptListRow,
    clientId?: string | null,
    activeIntents: readonly string[] = [],
): string {
    const normalizedText = (row.text ?? "")
        .trim()
        .replace(/\s+/g, " ")
        .toLowerCase();
    const normalizedProduct = (row.product ?? "").trim().toLowerCase();
    const storedIntent = (row.intent ?? "").trim();
    const normalizedIntent = resolveCanonicalIntent(storedIntent, activeIntents) ?? storedIntent;
    const canonicalLanguage = (row.language ?? "").trim();

    return JSON.stringify([
        (clientId ?? row.client_id ?? "").trim(),
        (row.topic_id ?? "").trim(),
        normalizedText,
        normalizedProduct,
        normalizedIntent,
        canonicalLanguage,
    ]);
}

export function canRemoveLogicalPromptDimensionVariants(
    uniqueDimensionValueCount: number,
    removalVariantCount: number,
    totalVariantCount: number,
): boolean {
    return uniqueDimensionValueCount > 1
        && removalVariantCount > 0
        && removalVariantCount < totalVariantCount;
}
