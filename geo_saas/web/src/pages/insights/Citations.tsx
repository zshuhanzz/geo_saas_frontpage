import CitationDashboard from "@/components/insights/CitationDashboard";
import { useSaaS } from "@/contexts/SaaSContext";
import { useInsightsFilters } from "../Insights";

export default function Citations() {
    const { clientId } = useSaaS();
    const {
        dateFrom,
        dateTo,
        interval,
        selectedTopics,
        selectedPlatforms,
        selectedCountries,
        selectedPromptTypes,
        filtersReady,
    } = useInsightsFilters();

    return (
        <CitationDashboard
            clientId={clientId}
            filtersReady={filtersReady}
            filters={{
                dateFrom,
                dateTo,
                interval,
                topicIds: selectedTopics,
                platforms: selectedPlatforms,
                countries: selectedCountries,
                promptTypes: selectedPromptTypes,
            }}
            mode="sidebar"
        />
    );
}
