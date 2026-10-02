import type { WizardFormState } from "../schema";

function stableStringify(value: unknown): string {
    if (value === null || typeof value !== "object") return JSON.stringify(value);
    if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
    const obj = value as Record<string, unknown>;
    return `{${Object.keys(obj).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(obj[key])}`).join(",")}}`;
}

function hashString(value: string): string {
    let h1 = 0x811c9dc5;
    let h2 = 0x01000193;
    for (let i = 0; i < value.length; i += 1) {
        const code = value.charCodeAt(i);
        h1 ^= code;
        h1 = Math.imul(h1, 0x01000193);
        h2 = Math.imul(h2 ^ code, 0x85ebca6b);
    }
    return `${(h1 >>> 0).toString(16).padStart(8, "0")}${(h2 >>> 0).toString(16).padStart(8, "0")}`;
}

export function fingerprint(value: unknown): string {
    return hashString(stableStringify(value));
}

export function subredditTargetingInputFingerprint(formState: WizardFormState, mode: string, keywords: string, manualSubreddits: string): string {
    return fingerprint({
        step: "subreddit_targeting",
        mode,
        keywords,
        manualSubreddits,
        topic_ids: formState.topic_ids || [],
        prompt_ids: formState.prompt_ids || [],
        content_type: formState.default || formState.content_type || "",
    });
}

export function redditDiscoveryInputFingerprint(formState: WizardFormState): string {
    const selectedSubreddits = (formState.subreddit_targeting as Record<string, unknown> | undefined)?.selected_subreddits;
    return fingerprint({
        step: "reddit_discovery",
        subreddit_targeting_fingerprint: (formState.subreddit_targeting as Record<string, unknown> | undefined)?.fingerprint || null,
        selected_subreddits: Array.isArray(selectedSubreddits) ? selectedSubreddits.slice(0, 1) : [],
        topic_ids: formState.topic_ids || [],
        prompt_ids: formState.prompt_ids || [],
        content_type: formState.default || formState.content_type || "",
    });
}

export function promptArtifactInputFingerprint(formState: WizardFormState): string {
    return fingerprint({
        step: "prompt_artifact_preparation",
        reddit_discovery_fingerprint: (formState.reddit_discovery as Record<string, unknown> | undefined)?.fingerprint || null,
        prompt_ids: formState.prompt_ids || [],
        topic_ids: formState.topic_ids || [],
    });
}

export function normalizeSubredditKey(item: unknown): string {
    const row = item && typeof item === "object" ? item as Record<string, unknown> : {};
    const raw = String(row.display_name || row.name || "").trim().toLowerCase();
    return raw.replace(/^r\//, "");
}

export function redditRulesReviewComplete(discovery: unknown): boolean {
    const payload = discovery && typeof discovery === "object" ? discovery as Record<string, unknown> : {};
    const subreddits = Array.isArray(payload.subreddits) ? payload.subreddits : [];
    if (subreddits.length === 0) return false;
    return subreddits.every((item) => {
        const row = item && typeof item === "object" ? item as Record<string, unknown> : {};
        if (row.rules_status === "verified") return true;
        if (row.rules_skip_confirmed === true) return true;
        const manual = row.rules_manual_override;
        if (typeof manual === "string") return manual.trim().length > 0;
        if (Array.isArray(manual)) return manual.length > 0;
        return false;
    });
}
