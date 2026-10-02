import type {
    PromptAllowedValue,
    PromptImportCommitOut,
    PromptImportPreviewOut,
    PromptImportUndoOut,
} from "@/lib/api/prompts";

export interface PromptImportState {
    clientId: string;
    file: File | null;
    preview: PromptImportPreviewOut | null;
    previewStale: boolean;
    committed: PromptImportCommitOut | null;
    undoResult: PromptImportUndoOut | null;
}

export function createPromptImportState(clientId: string): PromptImportState {
    return {
        clientId,
        file: null,
        preview: null,
        previewStale: false,
        committed: null,
        undoResult: null,
    };
}

export function selectPromptImportFile(
    state: PromptImportState,
    file: File | null,
): PromptImportState {
    return {
        ...state,
        file,
        preview: null,
        previewStale: false,
        committed: null,
        undoResult: null,
    };
}

export function resetPromptImportForWorkspace(
    _state: PromptImportState,
    clientId: string,
): PromptImportState {
    return createPromptImportState(clientId);
}

export function applyPreview(
    state: PromptImportState,
    preview: PromptImportPreviewOut,
): PromptImportState {
    return { ...state, preview, previewStale: false, committed: null, undoResult: null };
}

export function applyStalePreview(
    state: PromptImportState,
    preview: PromptImportPreviewOut,
): PromptImportState {
    return { ...state, preview, previewStale: true, committed: null, undoResult: null };
}

export function applyCommittedImport(
    state: PromptImportState,
    committed: PromptImportCommitOut,
): PromptImportState {
    return { ...state, committed, preview: committed.preview, previewStale: false, undoResult: null };
}

export function applyUndoResult(
    state: PromptImportState,
    undoResult: PromptImportUndoOut,
): PromptImportState {
    return { ...state, undoResult };
}

export function canCommitPromptImport(state: PromptImportState): boolean {
    if (!state.file || !state.preview || state.previewStale || state.committed) return false;
    return state.preview.action_counts.invalid === 0
        && state.preview.action_counts.conflict === 0;
}

export function isPromptImportStateOwned(state: PromptImportState, clientId: string): boolean {
    return Boolean(clientId) && state.clientId === clientId;
}

export function getOwnedPromptImportState(
    state: PromptImportState,
    clientId: string,
): PromptImportState {
    return isPromptImportStateOwned(state, clientId) ? state : createPromptImportState(clientId);
}

export function canCommitPromptImportForClient(state: PromptImportState, clientId: string): boolean {
    return isPromptImportStateOwned(state, clientId) && canCommitPromptImport(state);
}

export function paginatePromptImportRows<T extends { row_number: number }>(
    rows: readonly T[],
    requestedPage: number,
    pageSize: number,
): { rows: T[]; page: number; pageCount: number } {
    const ordered = [...rows].sort((left, right) => left.row_number - right.row_number);
    const safePageSize = Math.max(1, Math.floor(pageSize));
    const pageCount = Math.max(1, Math.ceil(ordered.length / safePageSize));
    const page = Math.min(Math.max(0, Math.floor(requestedPage)), pageCount - 1);
    return {
        rows: ordered.slice(page * safePageSize, (page + 1) * safePageSize),
        page,
        pageCount,
    };
}

export function lazyPromptImportVariants<V, T extends { row_number: number; variants?: readonly V[] }>(
    row: T,
    expandedRowNumber: number | null,
): readonly V[] {
    return row.row_number === expandedRowNumber ? row.variants || [] : [];
}

export function summarizePromptImport(preview: PromptImportPreviewOut) {
    return {
        inputRows: preview.input_row_count,
        expandedVariants: preview.expanded_variant_count,
        quotaImpact: preview.quota_after - preview.quota_before,
        quotaBefore: preview.quota_before,
        quotaAfter: preview.quota_after,
        quotaLimit: preview.quota_limit,
        create: preview.action_counts.create,
        skip: preview.action_counts.skip,
        conflict: preview.action_counts.conflict,
        invalid: preview.action_counts.invalid,
    };
}

export function groupAllowedValues(
    rows: readonly PromptAllowedValue[],
    searchQuery = "",
): Record<string, PromptAllowedValue[]> {
    const query = searchQuery.trim().normalize("NFKC").toLocaleLowerCase();
    const result: Record<string, PromptAllowedValue[]> = {};
    for (const row of rows) {
        const haystack = [row.type, row.value, row.label, row.parent_type, row.parent_value, row.notes]
            .join(" ")
            .normalize("NFKC")
            .toLocaleLowerCase();
        if (query && !haystack.includes(query)) continue;
        (result[row.type] ??= []).push(row);
    }
    return result;
}
