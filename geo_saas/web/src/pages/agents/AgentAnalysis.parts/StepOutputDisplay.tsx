/** Generic renderer for step output data */
export function StepOutputDisplay({ data }: { data: any }) {
    if (!data || typeof data !== "object") return null;
    const entries = Object.entries(data).filter(([, v]) => v != null && v !== "");
    if (entries.length === 0) return null;

    return (
        <div className="mt-1.5 space-y-1 max-h-60 overflow-y-auto">
            {entries.map(([key, value]) => (
                <div key={key} className="rounded border bg-background/50 p-2">
                    <div className="font-mono text-[10px] text-primary/80 mb-0.5">{key}</div>
                    {typeof value === "string" ? (
                        value.length > 200 ? (
                            <details>
                                <summary className="text-[11px] text-muted-foreground cursor-pointer select-none">
                                    {value.slice(0, 150)}...
                                </summary>
                                <pre className="mt-1 text-[10px] text-muted-foreground whitespace-pre-wrap break-all max-h-40 overflow-y-auto font-mono">
                                    {value}
                                </pre>
                            </details>
                        ) : (
                            <p className="text-[11px] text-muted-foreground whitespace-pre-wrap">{value}</p>
                        )
                    ) : (
                        <pre className="text-[10px] text-muted-foreground whitespace-pre-wrap break-all font-mono">
                            {JSON.stringify(value, null, 2)}
                        </pre>
                    )}
                </div>
            ))}
        </div>
    );
}
