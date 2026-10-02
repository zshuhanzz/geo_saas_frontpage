import { Loader2, CheckCircle, XCircle, Database } from "lucide-react";

export function StatusIcon({ status }: { status: string }) {
    if (status === "RUNNING") return <Loader2 className="h-4 w-4 animate-spin text-primary" />;
    if (status === "COMPLETED") return <CheckCircle className="h-4 w-4 text-emerald-500" />;
    if (status === "DRAFT") return <Database className="h-4 w-4 text-muted-foreground" />;
    return <XCircle className="h-4 w-4 text-destructive" />;
}
