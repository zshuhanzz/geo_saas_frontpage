// Pure helpers extracted from SettingsPage.tsx (Phase 3B.2).

export function domainToUrl(domain: string): string {
    const clean = (domain || "").trim();
    if (!clean) return "";
    if (clean.startsWith("http://") || clean.startsWith("https://")) return clean;
    return `https://${clean}`;
}
