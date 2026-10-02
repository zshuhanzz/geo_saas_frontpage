export interface Template {
    id: string; // backend mapping template_id
    run_id?: string; // specific task override
    name: string;
    description?: string;
    icon: string;
    data_domains: string[];
    default_prompt: string;
    is_builtin: boolean;
    is_active?: boolean;
    sort_order: number;
    cron_expression?: string;
    cron_timezone?: string;
    scheduler_job_name?: string;
    schedule_enabled?: boolean;
    chart_requests?: any[];
    filters?: any;
    /** Data-driven visibility gate. See wizard_config JSON on geo_report_templates.
     *  Example: { has_shadow_brands: true } — template only renders for OEM clients. */
    wizard_config?: { visibility_condition?: Record<string, boolean> } & Record<string, any>;
}

export interface RunRecord {
    id: string;
    task_name: string;
    task_type?: string;
    status: "RUNNING" | "COMPLETED" | "FAILED" | "DRAFT";
    triggered_by: string;
    started_at: string;
    completed_at?: string;
    created_at?: string;
    template_id?: string;
    error_message?: string;
    inputs?: any;
    output?: any;
    report_output?: {
        charts: any[];
        insights_markdown: string;
        variables: Record<string, string>;
        quality_score?: {
            data_accuracy_score?: number;
            consistency_score?: number;
            completeness_score?: number;
            overall_score?: number;
            summary?: string;
            issues?: string[];
        };
        // Opportunity discovery structured output
        topic_quadrants?: any[];
        content_opportunities?: any[];
        platform_recommendations?: any[];
    };
    status_logs?: Array<{ label?: string; step?: number; event?: string; ts?: string }>;
    workflow_steps?: Array<{ step: number; name: string; label: string; status: string }>;
    // Derived from inputs for backwards compat in UI
    domains?: string[];
}

export interface PaginationMeta {
    page: number;
    page_size: number;
    total: number;
    pages: number;
}
