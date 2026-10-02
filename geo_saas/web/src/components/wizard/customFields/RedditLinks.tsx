import { ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";
import { normalizeSubredditKey } from "./redditResearchUtils";

function subredditName(value: unknown): string {
    if (typeof value === "string") return normalizeSubredditKey({ name: value });
    if (value && typeof value === "object") return normalizeSubredditKey(value);
    return "";
}

function redditUrl(name: string, path = ""): string {
    const clean = subredditName(name);
    return `https://www.reddit.com/r/${clean}/${path}`;
}

export function SubredditNameLink({ item, className = "" }: { item: unknown; className?: string }) {
    const name = subredditName(item);
    if (!name) return null;
    return (
        <a
            href={redditUrl(name)}
            target="_blank"
            rel="noreferrer"
            className={`inline-flex items-center gap-1 hover:text-primary hover:underline ${className}`}
        >
            r/{name}
            <ExternalLink className="h-3 w-3" />
        </a>
    );
}

export function SubredditQuickLinks({ item, rulesSourceUrl }: { item: unknown; rulesSourceUrl?: string }) {
    const { t } = useTranslation("wizard");
    const name = subredditName(item);
    if (!name) return null;
    const links = [
        { key: "subreddit", label: t("redditResearchLinks.subreddit"), href: redditUrl(name) },
        { key: "about", label: t("redditResearchLinks.about"), href: redditUrl(name, "about/") },
        { key: "wiki", label: t("redditResearchLinks.wiki"), href: redditUrl(name, "wiki/index/") },
    ];
    if (rulesSourceUrl) {
        links.push({ key: "rulesSource", label: t("redditResearchLinks.rulesSource"), href: rulesSourceUrl });
    }
    return (
        <div className="mt-2 flex flex-wrap gap-1.5">
            {links.map((link) => (
                <a
                    key={link.key}
                    href={link.href}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 rounded-md border border-border/70 bg-background/50 px-2 py-1 text-[10px] font-medium text-muted-foreground transition hover:border-primary/40 hover:text-primary"
                >
                    {link.label}
                    <ExternalLink className="h-3 w-3" />
                </a>
            ))}
        </div>
    );
}

export function RedditLinkedText({ children, className = "" }: { children: string; className?: string }) {
    const text = String(children || "");
    const parts: Array<string | { name: string; raw: string }> = [];
    const re = /(^|[\s(])\/?r\/([A-Za-z0-9_]+)/g;
    let last = 0;
    let match: RegExpExecArray | null;
    while ((match = re.exec(text)) !== null) {
        const prefix = match[1] || "";
        const rawStart = match.index + prefix.length;
        if (rawStart > last) parts.push(text.slice(last, rawStart));
        const raw = match[0].slice(prefix.length);
        parts.push({ name: match[2], raw });
        last = rawStart + raw.length;
    }
    if (last < text.length) parts.push(text.slice(last));
    if (parts.length === 0) return <span className={className}>{text}</span>;
    return (
        <span className={className}>
            {parts.map((part, idx) => (
                typeof part === "string" ? part : (
                    <a
                        key={`${part.name}-${idx}`}
                        href={redditUrl(part.name)}
                        target="_blank"
                        rel="noreferrer"
                        className="font-medium text-primary hover:underline"
                    >
                        {part.raw}
                    </a>
                )
            ))}
        </span>
    );
}
