from typing import Dict, Any
from .base import BaseUnpacker

class GeminiUnpacker(BaseUnpacker):
    def unpack(self, full_response: Dict[str, Any]) -> Dict[str, Any]:
        response = full_response.get("response", {})
        result = response.get("result", {})
        data = result if result else response

        return {
            "text": data.get("text"),
            "html": data.get("html"),
            "markdown": data.get("markdown"),
            "sources": data.get("sources"),
            # Gemini typically doesn't have shopping cards in standard text-heavy responses,
            # but we map it if present.
            "shopping_cards": data.get("shoppingCards") or data.get("shopping_cards"), 
            "places": data.get("places"),
            "entities": data.get("entities"),
            "search_queries": data.get("searchQueries"),
            "citation_pills": None # Not applicable
        }
