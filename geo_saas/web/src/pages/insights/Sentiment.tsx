import SentimentDashboard from "@/components/insights/SentimentDashboard";
import { useSaaS } from "@/contexts/SaaSContext";
import { useInsightsFilters } from "../Insights";

export default function Sentiment() {
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
        <SentimentDashboard
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
