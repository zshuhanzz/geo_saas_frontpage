import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { useSaaS } from "@/contexts/SaaSContext";
import { trackSaaSAuditEvent } from "@/lib/api";

export function SaaSAuditTracker() {
    const location = useLocation();
    const { clientId } = useSaaS();
    const lastEventKey = useRef<string>("");

    useEffect(() => {
        if (!clientId) return;
        const route = location.pathname;
        const eventKey = `${clientId}:${route}`;
        if (lastEventKey.current === eventKey) return;
        lastEventKey.current = eventKey;

        trackSaaSAuditEvent({
            client_id: clientId,
            event_type: "page_view",
            action_key: "page.view",
            action_label: "Page View",
            route,
            method: "GET",
            metadata: { pathname: location.pathname },
        });
    }, [clientId, location.pathname]);

    return null;
}
