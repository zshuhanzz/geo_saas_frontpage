/**
 * useWizardFormState — unified form state reducer for the schema-driven wizard.
 *
 * Replaces the 20+ `useState` hooks that used to live in TemplateConfigModal
 * and ContentPipelineModal with a single reducer keyed by field key. Handles:
 *
 *   - Setting a single field (dispatches `depends_on` recomputation)
 *   - Bulk replacement (for reset / template switch)
 *   - Dirty tracking (so custom compute_default logic can skip recompute if
 *     the user has explicitly edited the field — we NEVER clobber user edits)
 *   - Running the declarative `compute_default` pass from `fieldComputers.ts`
 *
 * The reducer lives outside the component so unit tests can exercise it
 * without React. The hook wraps it and wires up `useMemo` caching of the
 * dependency graph so we don't walk every field on every keystroke.
 */
import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import { runFieldComputer } from "./fieldComputers";
import type {
    ResolvedWizardStep,
    WizardFieldSchema,
    WizardFormState,
    WizardRenderContext,
} from "./schema";

// ─── Reducer ─────────────────────────────────────────────────────────

export type WizardFormAction =
    | { type: "set_field"; key: string; value: unknown; userEdited?: boolean }
    | { type: "bulk_replace"; state: WizardFormState; dirty?: Set<string> }
    | { type: "mark_clean"; key: string }
    | { type: "reset" };

export interface WizardFormInternalState {
    values: WizardFormState;
    /** Fields the user has explicitly edited — compute_default will NOT
     *  overwrite these on dependency recompute. */
    dirty: Set<string>;
}

function reducer(
    state: WizardFormInternalState,
    action: WizardFormAction,
): WizardFormInternalState {
    switch (action.type) {
        case "set_field": {
            // Short-circuit reference-equality no-op sets so downstream
            // effects do not fire for a no-change write.
            if (state.values[action.key] === action.value) return state;
            const nextDirty = new Set(state.dirty);
            if (action.userEdited !== false) nextDirty.add(action.key);
            return {
                values: { ...state.values, [action.key]: action.value },
                dirty: nextDirty,
            };
        }
        case "bulk_replace":
            return {
                values: { ...action.state },
                dirty: action.dirty ? new Set(action.dirty) : new Set(),
            };
        case "mark_clean": {
            if (!state.dirty.has(action.key)) return state;
            const nextDirty = new Set(state.dirty);
            nextDirty.delete(action.key);
            return { values: state.values, dirty: nextDirty };
        }
        case "reset":
            return { values: {}, dirty: new Set() };
        default:
            return state;
    }
}

// ─── Dependency graph ────────────────────────────────────────────────

/** Flatten all fields across every resolved step into one list. */
function collectFields(steps: ResolvedWizardStep[]): WizardFieldSchema[] {
    const out: WizardFieldSchema[] = [];
    for (const step of steps) {
        for (const f of step.fields) out.push(f);
    }
    return out;
}

/**
 * Build a reverse dependency map: for each field key, the list of *other*
 * fields whose `compute_default` depends on it. O(n²) in the absolute worst
 * case but n is ~20, so we do not care.
 */
function buildReverseDependencyGraph(
    fields: WizardFieldSchema[],
): Map<string, WizardFieldSchema[]> {
    const graph = new Map<string, WizardFieldSchema[]>();
    for (const f of fields) {
        if (!f.depends_on || !f.compute_default) continue;
        for (const dep of f.depends_on) {
            const existing = graph.get(dep) || [];
            existing.push(f);
            graph.set(dep, existing);
        }
    }
    return graph;
}

// ─── Hook ────────────────────────────────────────────────────────────

export interface UseWizardFormStateOptions {
    /** Resolved (visible + hidden) steps — used to collect the full field list. */
    steps: ResolvedWizardStep[];
    /** Initial state (usually produced by `seedInitialFormState`). */
    initialState: WizardFormState;
    /** Render context forwarded to every `compute_default` computer. */
    context: WizardRenderContext;
}

export interface UseWizardFormStateResult {
    /** Current form state. */
    values: WizardFormState;
    /** Set a specific field. Re-runs dependents' `compute_default` if they
     *  have NOT been user-edited. */
    setField: (key: string, value: unknown, userEdited?: boolean) => void;
    /** Replace the entire state. Used for "reset" / "load template". */
    reset: (next?: WizardFormState) => void;
    /** For custom field components that need raw dispatch access. */
    dispatch: React.Dispatch<WizardFormAction>;
    /** Manually mark a field as clean (dependency-recompute eligible). */
    markClean: (key: string) => void;
    /** Internal state for debugging. */
    internal: WizardFormInternalState;
}

export function useWizardFormState(
    opts: UseWizardFormStateOptions,
): UseWizardFormStateResult {
    const fields = useMemo(() => collectFields(opts.steps), [opts.steps]);
    const reverseGraph = useMemo(
        () => buildReverseDependencyGraph(fields),
        [fields],
    );
    const fieldByKey = useMemo(() => {
        const m = new Map<string, WizardFieldSchema>();
        for (const f of fields) m.set(f.key, f);
        return m;
    }, [fields]);

    const [internal, dispatch] = useReducer(reducer, {
        values: opts.initialState,
        dirty: new Set<string>(),
    } as WizardFormInternalState);

    // ── Bug fix (2026-04-20) — async initialState re-seed ─────────────
    // `useReducer` consumes `initialState` ONLY on first mount. The wizard
    // shell computes `seededState` from fetched workflow_config + the
    // template's wizard_config.steps[*].default_*  overrides, but that
    // fetch is async. On first render, seededState = {} because
    // `resolvedAll = []` (definitions not loaded yet). When definitions
    // arrive, seededState rebuilds with real defaults — but `useReducer`
    // has already locked in the empty `{}`, so Wizard defaults like
    // `default_goal = "channel_performance"` or `default_lenses = [...]`
    // never materialise in form state → UI shows "Not set" / all-unchecked.
    //
    // Fix: when the upstream initialState identity changes AND the user
    // hasn't dirtied anything yet, bulk-replace form state. This is
    // conservative — user edits are never overwritten.
    const lastInitialStateRef = useRef(opts.initialState);
    useEffect(() => {
        if (lastInitialStateRef.current === opts.initialState) return;
        lastInitialStateRef.current = opts.initialState;
        if (internal.dirty.size > 0) return;  // user already started editing; do not stomp
        if (Object.keys(opts.initialState).length === 0) return;  // empty seed; nothing to apply
        dispatch({ type: "bulk_replace", state: opts.initialState });
    // Only react to initialState identity change. dirty.size read-only
    // guard (stale read is OK since dispatch is idempotent on rerun).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [opts.initialState]);

    // Keep a stable ref to the latest context so computer functions don't
    // capture a stale value during dependency recompute.
    const contextRef = useRef(opts.context);
    contextRef.current = opts.context;

    const setField = useCallback(
        (key: string, value: unknown, userEdited: boolean = true) => {
            dispatch({ type: "set_field", key, value, userEdited });
        },
        [],
    );

    const reset = useCallback((next?: WizardFormState) => {
        if (next) {
            dispatch({ type: "bulk_replace", state: next });
        } else {
            dispatch({ type: "reset" });
        }
    }, []);

    const markClean = useCallback((key: string) => {
        dispatch({ type: "mark_clean", key });
    }, []);

    // Dependency-recompute pass: whenever `values` changes, scan the reverse
    // graph and recompute any dependent field whose dirty flag is NOT set.
    // We use a ref+lastValues trick to detect exactly which key(s) flipped,
    // so we only recompute the subtree rooted at the changed keys.
    const lastValuesRef = useRef<WizardFormState>(internal.values);
    useEffect(() => {
        const prev = lastValuesRef.current;
        const next = internal.values;
        // Collect the flipped keys since last render.
        const flipped: string[] = [];
        const seenKeys = new Set<string>([
            ...Object.keys(prev),
            ...Object.keys(next),
        ]);
        for (const k of seenKeys) {
            if (prev[k] !== next[k]) flipped.push(k);
        }
        lastValuesRef.current = next;
        if (flipped.length === 0) return;

        const toRecompute = new Set<string>();
        for (const k of flipped) {
            const dependents = reverseGraph.get(k) || [];
            for (const dep of dependents) {
                if (internal.dirty.has(dep.key)) continue; // user edit wins
                toRecompute.add(dep.key);
            }
        }
        if (toRecompute.size === 0) return;

        // Apply recomputes in a single microtask to avoid a feedback loop.
        queueMicrotask(() => {
            for (const fieldKey of toRecompute) {
                const field = fieldByKey.get(fieldKey);
                if (!field || !field.compute_default) continue;
                try {
                    const newValue = runFieldComputer(
                        field.compute_default,
                        next,
                        field,
                        contextRef.current,
                    );
                    if (newValue !== undefined) {
                        dispatch({
                            type: "set_field",
                            key: fieldKey,
                            value: newValue,
                            userEdited: false,
                        });
                    }
                } catch (err) {
                    // Fail soft — a broken computer should not wedge the UI.
                    // eslint-disable-next-line no-console
                    console.error(
                        `[wizard] compute_default '${field.compute_default}' failed for '${fieldKey}':`,
                        err,
                    );
                }
            }
        });
    }, [internal.values, internal.dirty, reverseGraph, fieldByKey]);

    return { values: internal.values, setField, reset, dispatch, markClean, internal };
}
