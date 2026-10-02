// Helper: count unique prompts by text+topic_id
export function countUniquePrompts(arr: any[]): number {
    const seen = new Set<string>();
    for (const p of arr) seen.add(`${p.text}|||${p.topic_id}`);
    return seen.size;
}
