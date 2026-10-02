export interface CandidatePrompt {
    text: string;
    intent: string;
    selected: boolean;
    topic_id: string;
    topic_name: string;
    product: string;
    platforms: string[];
    countries: string[];
    language: string;
}

export interface GlobalPlatform {
    id: string;
    platform_id: string;
    display_name: string;
    supported_countries: string[];
    system_instructions: string | null;
}

export interface GlobalLanguage {
    id: string;
    language_code: string;
    language: string;
}
