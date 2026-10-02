export interface CitationMetricSort {
    metricKey: string;
    direction: "asc" | "desc";
}

export interface CitationQueryKeyInput {
    baseKey: string;
    rankingSort: CitationMetricSort;
    categorySort: CitationMetricSort;
    domainSearch: string;
    domainPage: number;
    domainSort: CitationMetricSort;
    pageSearch: string;
    pagePage: number;
    pageSort: CitationMetricSort;
}

export function buildCitationQueryKeys(input: CitationQueryKeyInput) {
    return {
        shareQueryKey: input.baseKey,
        rankingQueryKey: JSON.stringify([input.baseKey, input.rankingSort]),
        categoryQueryKey: JSON.stringify([input.baseKey, input.categorySort]),
        domainQueryKey: JSON.stringify([input.baseKey, input.domainSearch, input.domainPage, input.domainSort]),
        pageQueryKey: JSON.stringify([input.baseKey, input.pageSearch, input.pagePage, input.pageSort]),
    };
}
