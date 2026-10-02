/**
 * Global ``ErrorResponse`` model + typed exception class for GEO Admin.
 *
 * Phase 7c (2026-04-25): single source of truth for HTTP error shape across
 * every endpoint that ``client.ts`` calls. The Admin FastAPI app returns
 * errors via the default ``HTTPException`` body — i.e. ``{"detail": "..."}``
 * — so a single shape suffices. ``fetchJSON`` (in ``client.ts``) throws
 * ``ApiError`` instead of a bare ``Error`` so call-sites can branch on
 * ``err instanceof ApiError`` to recover ``detail`` + HTTP ``status``.
 *
 * Mirrors ``geo_saas/web/src/lib/api/_errors.ts`` — kept as two files (one
 * per project) rather than a shared package, to honour the monorepo's
 * "each service owns its own client" boundary.
 */

/** Wire shape returned by FastAPI's default ``HTTPException`` handler. */
export interface ErrorResponse {
    detail: unknown;
}

interface StructuredErrorDetail {
    code?: string;
    message?: string;
    [key: string]: unknown;
}

function parseErrorDetail(detail: unknown): {
    message: string;
    code?: string;
    structuredDetail: StructuredErrorDetail | null;
} {
    if (typeof detail === "string") {
        return { message: detail, structuredDetail: null };
    }
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
        const structuredDetail = detail as StructuredErrorDetail;
        const message = typeof structuredDetail.message === "string"
            ? structuredDetail.message
            : "Request failed";
        const code = typeof structuredDetail.code === "string" ? structuredDetail.code : undefined;
        return { message, code, structuredDetail };
    }
    return { message: "Request failed", structuredDetail: null };
}

/**
 * Typed exception thrown by ``fetchJSON`` when an HTTP response is not ok.
 * ``message`` is set to ``detail`` so existing call-sites that read
 * ``err.message`` continue to work unchanged.
 */
export class ApiError extends Error {
    public readonly detail: string;
    public readonly status: number;
    public readonly code?: string;
    public readonly structuredDetail: StructuredErrorDetail | null;

    constructor(detail: unknown, status: number) {
        const parsed = parseErrorDetail(detail);
        super(parsed.message);
        this.name = "ApiError";
        this.detail = parsed.message;
        this.status = status;
        this.code = parsed.code;
        this.structuredDetail = parsed.structuredDetail;
        Object.setPrototypeOf(this, ApiError.prototype);
    }
}
