from typing import Dict, Any

from .base import BaseUnpacker


class PerplexityUnpacker(BaseUnpacker):
    def unpack(self, full_response: Dict[str, Any]) -> Dict[str, Any]:
        data = self._result(full_response)

        places = data.get("places")
        hotels = data.get("hotels")
        if isinstance(places, list) and isinstance(hotels, list):
            combined_places = [*places, *hotels]
        else:
            combined_places = places or hotels

        entities = data.get("entities")
        if entities is None:
            entities = {
                "videos": data.get("videos"),
                "images": data.get("images"),
                "related_queries": data.get("related_queries") or data.get("relatedQueries"),
                "search_model_queries": data.get("search_model_queries") or data.get("searchModelQueries"),
            }

        sources = self._normalize_sources(data.get("sources"))
        citation_pills = self._first(data, "citationPills", "citation_pills")
        if citation_pills is None:
            citation_pills = self._citations_to_pills(data.get("citations"), sources)

        return {
            "text": data.get("text"),
            "html": data.get("html"),
            "markdown": data.get("markdown"),
            "sources": sources,
            "shopping_cards": self._first(data, "shopping_cards", "shoppingCards"),
            "places": combined_places,
            "entities": entities,
            "search_queries": self._first(
                data,
                "searchQueries",
                "search_queries",
                "search_model_queries",
                "searchModelQueries",
                "related_queries",
                "relatedQueries",
            ),
            "citation_pills": self._normalize_citation_pills(
                citation_pills
            ),
        }
