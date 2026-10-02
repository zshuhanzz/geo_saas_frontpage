from typing import Dict, Any

from .base import BaseUnpacker


class AIOverviewUnpacker(BaseUnpacker):
    def unpack(self, full_response: Dict[str, Any]) -> Dict[str, Any]:
        google_result = self._result(full_response)
        aioverview = self._first(google_result, "aioverview", "aiOverview", "ai_overview")

        if not isinstance(aioverview, dict):
            return {
                "text": None,
                "html": None,
                "markdown": None,
                "sources": [],
                "shopping_cards": None,
                "places": None,
                "entities": {
                    "aioverview_present": False,
                    "organic_results": google_result.get("organicResults"),
                    "people_also_ask": google_result.get("peopleAlsoAsk"),
                    "related_searches": google_result.get("relatedSearches"),
                },
                "search_queries": None,
                "citation_pills": [],
            }

        sources = self._normalize_sources(aioverview.get("sources"))
        citation_pills = aioverview.get("citationPills") or aioverview.get("citation_pills")
        if citation_pills is None:
            citation_pills = self._citations_to_pills(aioverview.get("citations"), sources)

        return {
            "text": aioverview.get("text"),
            "html": aioverview.get("html"),
            "markdown": aioverview.get("markdown"),
            "sources": sources,
            "shopping_cards": aioverview.get("shoppingCards") or aioverview.get("shopping_cards"),
            "places": None,
            "entities": {
                "aioverview_present": True,
                "videos": aioverview.get("videos"),
                "ads": aioverview.get("ads"),
                "organic_results": google_result.get("organicResults"),
                "people_also_ask": google_result.get("peopleAlsoAsk"),
                "related_searches": google_result.get("relatedSearches"),
            },
            "search_queries": google_result.get("relatedSearches"),
            "citation_pills": self._normalize_citation_pills(
                citation_pills
            ),
        }
