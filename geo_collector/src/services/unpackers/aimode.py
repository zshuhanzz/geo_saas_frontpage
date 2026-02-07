from typing import Dict, Any
from .base import BaseUnpacker

class AIModeUnpacker(BaseUnpacker):
    def unpack(self, full_response: Dict[str, Any]) -> Dict[str, Any]:
        response = full_response.get("response", {})
        result = response.get("result", {})
        data = result if result else response

        return {
            "text": data.get("text"),
            "html": data.get("html"),
            "markdown": data.get("markdown"),
            "sources": data.get("sources"),
            "shopping_cards": data.get("shopping_cards"), # snake_case mapping
            "places": data.get("places"),
            "entities": data.get("entities"),
            "search_queries": data.get("searchQueries"),  # check if this is snake_case in AI Mode? Sample showed standard.
            "citation_pills": None
        }
